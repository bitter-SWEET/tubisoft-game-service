"""Private worker-to-service result ingestion; never a client password endpoint."""
from __future__ import annotations
import asyncio,hmac,ipaddress,json,sqlite3
from dataclasses import dataclass,field
from pathlib import Path
from .ladder import LadderStore,LadderError,ConflictingReport,UnknownAccount,token,normalize

MAX_BODY=65536


@dataclass(frozen=True)
class WorkerGrant:
    worker:str
    secret:bytes=field(repr=False)
    products:tuple[str,...]=()

    def __post_init__(self):
        token(self.worker)
        if not isinstance(self.secret,bytes)or not 32<=len(self.secret)<=256 or any(c<33 or c>126 for c in self.secret):
            raise ValueError('Private printable worker key of at least 32 bytes required')
        if not isinstance(self.products,tuple)or not self.products:raise ValueError('Explicit worker product scope required')
        for product in self.products:token(product)


def load_grants(path:Path):
    if path.stat().st_size>16384:raise ValueError('Worker keyring too large')
    rows=json.loads(path.read_text())
    if not isinstance(rows,list)or not 1<=len(rows)<=32:raise ValueError('Bounded worker keyring required')
    grants=[]
    for row in rows:
        if not isinstance(row,dict)or set(row)!={'worker','key_file','products'}or not isinstance(row['products'],list):
            raise ValueError('Invalid worker keyring row')
        key=Path(row['key_file'])
        if not key.is_absolute():key=path.resolve().parent/key
        if key.stat().st_size>256:raise ValueError('Worker key too large')
        grants.append(WorkerGrant(row['worker'],key.read_bytes().strip(),tuple(row['products'])))
    if len({g.worker for g in grants})!=len(grants)or len({g.secret for g in grants})!=len(grants):
        raise ValueError('Unique worker names and credentials required')
    return tuple(grants)


def decode_document(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate result field')
            result[key]=value
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,
        parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite result JSON')))


def response(status,value):
    body=json.dumps(value,separators=(',',':')).encode()
    return ('HTTP/1.0 '+status+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body))+
        '\r\nConnection: close\r\n\r\n').encode()+body


class ResultsHandler:
    def __init__(self,store,grants):
        if not isinstance(store,LadderStore)or not isinstance(grants,tuple)or not grants:
            raise ValueError('Concrete result store and private worker grants required')
        if len(grants)>32 or any(not isinstance(g,WorkerGrant)for g in grants):raise ValueError('Bounded typed worker grants required')
        if len({g.worker for g in grants})!=len(grants)or len({g.secret for g in grants})!=len(grants):raise ValueError('Unique worker grants required')
        self.store,self.grants=store,grants;self.active=0

    async def __call__(self,reader,writer):
        status='400 Bad Request';value={'error':'invalid-result'}
        admitted=self.active<32
        if admitted:self.active+=1
        try:
            if not admitted:
                status='503 Service Unavailable';value={'error':'capacity'}
            else:
                header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),10)
                if len(header)>8192:raise ValueError('Oversized header')
                lines=header.decode('ascii').split('\r\n')
                if lines[0]not in('POST /v1/results HTTP/1.0','POST /v1/results HTTP/1.1'):raise ValueError('Unsupported result route')
                fields={}
                for line in lines[1:]:
                    if not line:continue
                    name,sep,field_value=line.partition(':');name=name.lower()
                    if not sep or name in fields:raise ValueError('Invalid/duplicate header')
                    fields[name]=field_value.strip()
                if 'transfer-encoding'in fields:raise ValueError('Unsupported transfer encoding')
                authorization=fields.get('authorization','').encode('ascii')
                grant=next((g for g in self.grants if hmac.compare_digest(authorization,b'Bearer '+g.secret)),None)
                if grant is None:
                    status='401 Unauthorized';value={'error':'worker-authentication-required'}
                else:
                    size=fields.get('content-length','')
                    if not size.isascii()or not size.isdigit()or not 1<=int(size)<=MAX_BODY:raise ValueError('Bounded content length required')
                    raw=await asyncio.wait_for(reader.readexactly(int(size)),10);document=normalize(decode_document(raw))
                    if (not isinstance(document,dict)or document.get('worker')!=grant.worker
                            or document.get('product')not in grant.products):
                        status='403 Forbidden';value={'error':'worker-scope'}
                    else:
                        receipt=await asyncio.to_thread(self.store.record,document)
                        status='201 Created'if receipt.inserted else '200 OK'
                        value={'inserted':receipt.inserted,'credited':receipt.credited}
        except ConflictingReport:status='409 Conflict';value={'error':'conflicting-result'}
        except UnknownAccount:status='422 Unprocessable Entity';value={'error':'unknown-account'}
        except (ValueError,TypeError,KeyError,UnicodeError,asyncio.TimeoutError,
                asyncio.IncompleteReadError,asyncio.LimitOverrunError):pass
        except ConnectionError:return
        except (sqlite3.Error,OSError):status='503 Service Unavailable';value={'error':'result-store-unavailable'}
        finally:
            if admitted:self.active-=1
            try:writer.write(response(status,value));await writer.drain()
            except ConnectionError:pass
            writer.close()
            try:await writer.wait_closed()
            except ConnectionError:pass


async def serve(store,grants,*,bind='127.0.0.1',port=8081):
    if not ipaddress.ip_address(bind).is_loopback:raise ValueError('Worker results listener must be loopback; use an authenticated tunnel')
    server=await asyncio.start_server(ResultsHandler(store,grants),bind,port,limit=8192)
    async with server:await server.serve_forever()
