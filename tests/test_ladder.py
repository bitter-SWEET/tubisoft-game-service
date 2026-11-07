import asyncio,copy,concurrent.futures,json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import closing
from ubisoft.accounts import create_account,verify_account,backup_database
from ubisoft.ladder import LadderStore,LadderError,ConflictingReport,UnknownAccount,COUNTERS
from ubisoft.results_api import ResultsHandler,WorkerGrant


def report(*,mode='assault',round=1,product='GHOSTRECON2PS2'):
    players=[]
    for slot,name,team,kills in((0,'First',2,3),(1,'Second',3,1)):
        counters={k:0 for k in COUNTERS};counters.update(kills=kills,deaths=1,shots=4,hits=5,play_ms=1000)
        players.append(dict(slot=slot,account=name,team=team,stats=counters))
    return dict(schema='tubisoft-match-result-v1',product=product,mode=mode,worker='fixture-worker',match='fixture-match',
        round=round,winner=2,ranked=True,players=players)


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'accounts.sqlite3'
        for user in('First','Second'):create_account(self.path,user,'fixture-password')
        self.store=LadderStore(self.path)

    def test_record_retry_and_casefold_keep_shared_credentials_and_credit_once(self):
        document=report();self.assertTrue(self.store.record(document).inserted)
        retry=copy.deepcopy(document);retry['players'].reverse();retry['players'][0]['account']='SECOND'
        receipt=self.store.record(retry);self.assertFalse(receipt.inserted);self.assertTrue(receipt.credited)
        rows=self.store.leaderboard('GHOSTRECON2PS2')
        self.assertEqual([(r['name'],r['rounds_played'],r['kills'],r['team_wins'])for r in rows],[('First',1,3,1),('Second',1,1,0)])
        self.assertTrue(verify_account(self.path,'FIRST','fixture-password'))
        self.assertEqual(self.store.account_statistics('FIRST','GHOSTRECON2PS2'),rows[0])
        self.assertIsNone(self.store.account_statistics('absent','GHOSTRECON2PS2'))

    def test_conflicting_retry_is_atomic_and_does_not_change_totals(self):
        self.store.record(report());changed=report();changed['players'][0]['stats']['kills']=999
        with self.assertRaises(ConflictingReport):self.store.record(changed)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2')[0]['kills'],3)

    def test_concurrent_retries_have_one_winner(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
            receipts=list(pool.map(lambda _:self.store.record(report()),range(4)))
        self.assertEqual(sum(r.inserted for r in receipts),1)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2')[0]['rounds_played'],1)

    def test_guest_or_mixed_round_is_retained_without_account_ladder_credit(self):
        document=report();document['ranked']=False;document['players'][0]['account']=None
        self.assertFalse(self.store.record(document).credited)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2'),[])
        document=report(round=2);document['players'][0]['account']=None
        with self.assertRaises(LadderError):self.store.record(document)

    def test_unknown_account_rolls_back_entire_round_and_can_retry_after_creation(self):
        document=report();document['players'][1]['account']='Third'
        with self.assertRaises(UnknownAccount):self.store.record(document)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2'),[])
        create_account(self.path,'Third','fixture-password')
        self.assertTrue(self.store.record(document).inserted)

    def test_product_and_mode_boards_share_accounts_without_mixing_titles(self):
        self.store.record(report());self.store.record(report(mode='sabotage',round=2))
        self.store.record(report(product='XIIIPS2US',mode='deathmatch',round=3))
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2')[0]['rounds_played'],2)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2',mode='assault')[0]['rounds_played'],1)
        self.assertEqual(self.store.leaderboard('XIIIPS2US')[0]['rounds_played'],1)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2',limit=1,offset=1)[0]['rank'],2)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2',mode='onslaught'),[])

    def test_schema_rejects_unknown_identity_and_statistics_fields(self):
        rows=[]
        for key,value in(('winner',2.0),('winner',True),('round',0),('ranked','yes'),('players',[])):
            d=report();d[key]=value;rows.append(d)
        for value in(-1,True,2**31):
            d=report();d['players'][0]['stats']['kills']=value;rows.append(d)
        d=report();d['players'][1]['account']='FIRST';rows.append(d)
        d=report();d['players'][0]['password']='refused';rows.append(d)
        d=report();d['peer']='refused';rows.append(d)
        for row in rows:
            with self.subTest(row=row),self.assertRaises(LadderError):self.store.record(row)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2'),[])

    def test_account_backup_includes_ladder_tables(self):
        self.store.record(report());destination=self.path.parent/'backup.sqlite3'
        backup_database(self.path,destination);restored=LadderStore(destination)
        self.assertEqual(restored.leaderboard('GHOSTRECON2PS2'),self.store.leaderboard('GHOSTRECON2PS2'))
        with closing(sqlite3.connect(destination))as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)


class ResultsAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'accounts.sqlite3'
        for name in('First','Second'):create_account(self.path,name,'fixture-password')
        self.store=LadderStore(self.path);self.key=b'fixture-key-material-for-loopback-tests-only'
        handler=ResultsHandler(self.store,(WorkerGrant('fixture-worker',self.key,('GHOSTRECON2PS2',)),))
        self.server=await asyncio.start_server(handler,'127.0.0.1',0,limit=8192)
        self.addAsyncCleanup(self.server.wait_closed);self.addCleanup(self.server.close)

    async def request(self,document=None,*,key=None,raw=None):
        body=raw if raw is not None else json.dumps(document or report()).encode()
        reader,writer=await asyncio.open_connection('127.0.0.1',self.server.sockets[0].getsockname()[1])
        token=self.key if key is None else key
        writer.write(b'POST /v1/results HTTP/1.0\r\nAuthorization: Bearer '+token+b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
        await writer.drain();data=await reader.read();writer.close();await writer.wait_closed()
        header,body=data.split(b'\r\n\r\n',1)
        return int(header.split(b' ')[1]),json.loads(body)

    async def test_authentication_worker_and_product_scope(self):
        self.assertEqual((await self.request(key=b'not-authorized'))[0],401)
        document=report();document['worker']='different-worker';self.assertEqual((await self.request(document))[0],403)
        document=report(product='XIIIPS2US');self.assertEqual((await self.request(document))[0],403)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2'),[])

    async def test_success_duplicate_conflict_and_unknown_account(self):
        self.assertEqual(await self.request(),(201,{'inserted':True,'credited':True}))
        self.assertEqual(await self.request(),(200,{'inserted':False,'credited':True}))
        document=report();document['winner']=3;self.assertEqual((await self.request(document))[0],409)
        document=report(round=2);document['players'][0]['account']='absent';self.assertEqual((await self.request(document))[0],422)

    async def test_malformed_and_duplicate_json_fields_do_not_persist(self):
        for raw in(b'{',b'{"schema":"one","schema":"two"}',b'[]',b'{"kills":NaN}'):
            self.assertEqual((await self.request(raw=raw))[0],400)
        self.assertEqual(self.store.leaderboard('GHOSTRECON2PS2'),[])


if __name__=='__main__':unittest.main()
