"""Dedicated GR2 discovery/join and worker expiry, using synthetic local state."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import time
import unittest

from ubisoft import router, service
from ubisoft.games.registry import GR2, XIII
from ubisoft.games.base import UnsupportedOperation
from ubisoft.gr2_worker import SCHEMA, game_description, read_worker
from ubisoft.rooms import RoomRegistry
from test_games import GSClient

PROFILE = replace(GR2, supports_rooms=True)


def record(now=100):
    return dict(schema=SCHEMA, run_id='a'*32, updated=now, ready=True,
                map='st01_map', mode='assault', address='192.0.2.1', port=3659,
                capacity=8, players=0, description=bytes(84).hex())


class WorkerTests(unittest.TestCase):
    def test_round_report_is_scoped_to_gr2_and_the_joined_dedicated_room(self):
        registry = RoomRegistry()
        # Use a genuine validated worker room, without any account state.
        with TemporaryDirectory() as directory:
            path = Path(directory)/'worker.json'
            path.write_text(json.dumps(record()))
            registry.worker_provider = lambda: read_worker(path, PROFILE, 100)
            room_id = int(registry.children(GR2.product)[0][2])
            room = registry.active_room(room_id, GR2.product)
            PROFILE.game_transition(room, [str(room_id)])
            for fields in ([], ['1'], [room_id], [str(room_id), 'extra'], [b'1000']):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    PROFILE.game_transition(room, fields)
            with self.assertRaises(ValueError):
                GR2.game_transition(room, [str(room_id)])
            with self.assertRaises(ValueError):
                PROFILE.game_transition(replace(room, dedicated=False), [str(room_id)])
            with self.assertRaises(UnsupportedOperation):
                XIII.game_transition(room, [str(room_id)])

    def test_native_description_layout_clears_password_and_sets_real_endpoint(self):
        source = bytearray(84)
        source[16:32] = b'private-fixture!'
        encoded = game_description('192.0.2.1', 3659, bytes(source))
        self.assertEqual(len(encoded), 84)
        self.assertEqual(encoded[16:32], bytes(16))
        self.assertEqual(encoded[76:80], b'\xc0\x00\x02\x01')
        self.assertEqual(struct.unpack_from('<H', encoded, 80)[0], 3659)
        self.assertEqual(struct.unpack_from('<I', encoded, 72)[0], 0)
        self.assertEqual(struct.unpack_from('<I', encoded, 44)[0], 1)

    def test_all_original_map_selectors_encode_without_changing_mode_or_endpoint(self):
        for index in range(10):
            mode='assault'if index<9 else'team-survival'
            payload=game_description('192.0.2.1',3659,bytes(84),map_id=f'st{index+1:02}_map',mode=mode)
            self.assertEqual(struct.unpack_from('<I',payload,0x20)[0],index)
            self.assertEqual(struct.unpack_from('<I',payload,0x2c)[0],1 if index<9 else 4)
            self.assertEqual(payload[0x4c:0x50],b'\xc0\x00\x02\x01')
            self.assertEqual(payload[0x10:0x20],bytes(16))
        for invalid in ('st00_map','st11_map','ST01_MAP','st1_map','other',None,[],True):
            with self.assertRaises(ValueError):game_description('192.0.2.1',3659,bytes(84),map_id=invalid)

    def test_map_change_refreshes_description_in_place_without_dropping_members(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'worker.json';path.write_text(json.dumps(record()))
            registry=RoomRegistry();registry.worker_provider=lambda:read_worker(path,PROFILE,100)
            first=registry.children(GR2.product)[0];room=registry.active_room(int(first[2]),GR2.product)
            member=('192.0.2.2','synthetic-member');room.members.add(member)
            removed=[];registry.add_remove_listener(lambda room:removed.append(room.room_id))
            for index in range(10):
                path.write_text(json.dumps(record()|{'map':f'st{index+1:02}_map','mode':'assault'if index<9 else'team-survival'}))
                refreshed=registry.children(GR2.product)[0]
                self.assertEqual(refreshed[2],first[2]);self.assertIn(member,room.members)
                self.assertEqual(struct.unpack_from('<I',room.info,0x20)[0],index)
                self.assertEqual(room.info,room.additional_info)
            self.assertEqual(removed,[])

    def test_survival_advertisement_uses_real_mode_and_preserves_unproved_neighbor(self):
        template=bytearray(84);struct.pack_into('<I',template,0x30,7)
        encoded=game_description('192.0.2.1',3659,bytes(template),mode='team-survival')
        self.assertEqual(struct.unpack_from('<I',encoded,0x2c)[0],4)
        self.assertEqual(struct.unpack_from('<I',encoded,0x30)[0],7)
        for unsupported in ('sabotage','no-rules',4,None,[],True):
            with self.assertRaises(ValueError):game_description('192.0.2.1',3659,bytes(template),mode=unsupported)

    def test_onslaught_and_survival_only_sandbox_follow_original_selectors(self):
        template=bytearray(84);struct.pack_into('<I',template,0x30,7)
        encoded=game_description('192.0.2.1',3659,bytes(template),mode='onslaught')
        self.assertEqual(struct.unpack_from('<I',encoded,0x2c)[0],3)
        self.assertEqual(struct.unpack_from('<I',encoded,0x30)[0],7)
        for unsupported in ('assault','onslaught'):
            with self.assertRaises(ValueError):
                game_description('192.0.2.1',3659,bytes(template),map_id='st10_map',mode=unsupported)
        with TemporaryDirectory()as folder:
            p=Path(folder)/'worker.json'
            for mode in ('assault','onslaught'):
                p.write_text(json.dumps(record()|dict(map='st10_map',mode=mode)))
                self.assertIsNone(read_worker(p,PROFILE,100))
            p.write_text(json.dumps(record()|dict(map='st10_map',mode='team-survival')))
            self.assertIsNotNone(read_worker(p,PROFILE,100))

    def test_mode_change_updates_name_and_enum_without_dropping_directory_members(self):
        with TemporaryDirectory()as directory:
            path=Path(directory)/'worker.json';path.write_text(json.dumps(record()))
            registry=RoomRegistry();registry.worker_provider=lambda:read_worker(path,PROFILE,100)
            first=registry.children(GR2.product)[0];room=registry.active_room(int(first[2]),GR2.product)
            member=('192.0.2.2','synthetic-member');room.members.add(member)
            path.write_text(json.dumps(record()|{'mode':'team-survival'}))
            updated=registry.children(GR2.product)[0]
            self.assertEqual(updated[2],first[2]);self.assertIn(member,room.members)
            self.assertEqual(updated[1],'Tubisoft GR2 Team Survival')
            self.assertEqual(struct.unpack_from('<I',room.info,0x2c)[0],4)
            path.write_text(json.dumps(record()|{'mode':'onslaught'}))
            updated=registry.children(GR2.product)[0]
            self.assertEqual(updated[2],first[2]);self.assertIn(member,room.members)
            self.assertEqual(room.name,'Tubisoft GR2 Onslaught')
            self.assertEqual(struct.unpack_from('<I',room.info,0x2c)[0],3)
            path.write_text(json.dumps(record()|{'mode':'sabotage'}))
            self.assertEqual(registry.children(GR2.product),[])

    def test_stale_stopped_invalid_and_default_disabled_workers_are_absent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'worker.json'
            for changes in ({'updated':94}, {'ready':False}, {'description':'00'}, {'map':'other'},
                            {'players':9}, {'port':0}, {'run_id':'bad'}, {'address':'0.0.0.0'}):
                path.write_text(json.dumps(record() | changes))
                self.assertIsNone(read_worker(path, PROFILE, 100))
            path.write_text(json.dumps(record()))
            self.assertIsNone(read_worker(path, GR2, 100))
            self.assertIsNotNone(read_worker(path, PROFILE, 101))
            path.unlink()
            self.assertIsNone(read_worker(path, PROFILE, 100))

    def test_native_counts_worker_restarts_and_expiry_are_scoped_and_remove_rooms(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'worker.json';path.write_text(json.dumps(record()))
            now=[100];registry=RoomRegistry()
            registry.worker_provider=lambda:read_worker(path, PROFILE, now[0])
            removed=[];registry.add_remove_listener(lambda room:removed.append(room.room_id))
            first=registry.children(GR2.product)[0]
            self.assertEqual(len(first),20)
            self.assertEqual(first[12:14],['8','0'])
            self.assertEqual(registry.children(XIII.product),[])
            room=registry.active_room(int(first[2]),GR2.product)
            room.members.add(('192.0.2.2','fixture'))
            self.assertEqual(room.group_fields()[13],'0')
            self.assertFalse(registry.bind_host(room,room.owner,room.peer_ip,object()))
            path.write_text(json.dumps(record() | {'players':1}))
            self.assertEqual(registry.children(GR2.product)[0][13],'1')
            path.write_text(json.dumps(record() | {'address':'192.0.2.3', 'port':3660, 'capacity':16}))
            registry.sync_worker()
            self.assertEqual((room.peer_ip, room.game_port, room.max_players), ('192.0.2.3', '3660', '16'))
            path.write_text(json.dumps(record() | {'run_id':'b'*32}))
            second=registry.children(GR2.product)[0]
            self.assertNotEqual(first[2],second[2])
            self.assertEqual(removed,[int(first[2])])
            now[0]=106
            self.assertEqual(registry.children(GR2.product),[])
            self.assertEqual(removed,[int(first[2]),int(second[2])])


class WorkerSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_game_listing_join_endpoint_and_expiry_retain_gs_session(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);state=root/'worker.json'
            state.write_text(json.dumps(record(time.time())))
            registry=RoomRegistry();registry.worker_provider=lambda:read_worker(state,PROFILE)
            keypath=root/'key.pem';service.ensure_key(keypath);private=router.load_key(keypath)
            pending={('127.0.0.1','fixture'):time.monotonic()+120}
            async def handle(reader,writer):
                await router.handle(reader,writer,private,10,root/'unused.sqlite3','127.0.0.1',port,
                                    pending,{},registry,game_profile=PROFILE)
            server=await asyncio.start_server(handle,'127.0.0.1',0)
            port=server.sockets[0].getsockname()[1]
            client=GSClient(*await asyncio.open_connection('127.0.0.1',port))
            try:
                await client.handshake(private)
                await client.send(0xd2,['Fixture','1','1.0','','0'])
                _,fields=await client.receive();self.assertEqual(fields,['210',['1']])
                await client.send(0xd1,['23',['1','','0']])
                _,fields=await client.receive();self.assertEqual(fields,['38',['23',['1','']]])
                _,fields=await client.receive();listing=fields[1][3]
                self.assertEqual(len(listing),1)
                roomid=listing[0][2]
                await client.send(0xd1,['24',[roomid,'','0','0',GR2.product]])
                _,fields=await client.receive();self.assertEqual(fields,['38',['24',[roomid,'']]])
                _,fields=await client.receive();self.assertEqual(fields[0],'53')
                await client.send(0xd1,['42',[bytes(28)]])
                _,fields=await client.receive();self.assertEqual(fields,['38',['42']])
                _,fields=await client.receive()
                self.assertEqual(fields,['56',[roomid,b'','3659','192.0.2.1','192.0.2.1']])
                # Retail client reports operation 34 immediately after the
                # endpoint handoff; no separate reply is consumed by its SDK.
                await client.send(0xd1,['34',[roomid]])
                await client.send(0x3a)
                header,_=await client.receive();self.assertEqual(header.message_type,0x3a)
                # Both retail clients sent operation 70 at the same round
                # boundary. It formerly fell through and closed GS sockets.
                pending[('127.0.0.1','otherfixture')] = time.monotonic()+120
                other = GSClient(*await asyncio.open_connection('127.0.0.1',port))
                try:
                    await other.handshake(private)
                    await other.send(0xd2,['OtherFixture','1','1.0','','0'])
                    _,fields=await other.receive();self.assertEqual(fields,['210',['1']])
                    await other.send(0xd1,['24',[roomid,'','0','0',GR2.product]])
                    await other.receive();await other.receive()
                    room=registry.active_room(int(roomid),GR2.product)
                    self.assertEqual(len(room.members),2)
                    for _ in range(2):
                        for joined in (client,other):
                            await joined.send(0xd1,['70',[roomid]])
                            await joined.send(0x3a)
                            header,fields=await joined.receive()
                            # No fabricated operation-70 ACK precedes the
                            # heartbeat, and neither connection reaches EOF.
                            self.assertEqual((header.message_type,fields),(0x3a,[]))
                        self.assertEqual(len(room.members),2)
                        self.assertIs(registry.active_room(int(roomid),GR2.product),room)
                    await client.send(0xd1,['8',[roomid]])
                    _,fields=await client.receive();self.assertEqual(fields,['38',['8',[roomid]]])
                    self.assertEqual(len(room.members),1)
                    for subtype in ('34','70'):await client.send(0xd1,[subtype,[roomid]])
                    await client.send(0x3a)
                    header,_=await client.receive();self.assertEqual(header.message_type,0x3a)
                    await client.send(0xd1,['24',[roomid,'','0','0',GR2.product]])
                    await client.receive();await client.receive()
                    self.assertEqual(len(room.members),2)
                finally:
                    other.writer.close();await other.writer.wait_closed()
                state.unlink();registry.sync_worker()
                _,fields=await client.receive();self.assertEqual(fields,['55',[roomid]])
                # A worker expiry/restart can race the client's last one-way
                # game/round report. It must not force a new account sign-in.
                for subtype in ('34','70'):await client.send(0xd1,[subtype,[roomid]])
                await client.send(0x3a)
                header,_=await client.receive();self.assertEqual(header.message_type,0x3a)
                state.write_text(json.dumps(record(time.time())|{'run_id':'b'*32}))
                new_id=registry.children(GR2.product)[0][2]
                self.assertNotEqual(new_id,roomid)
                await client.send(0xd1,['24',[new_id,'','0','0',GR2.product]])
                _,fields=await client.receive();self.assertEqual(fields,['38',['24',[new_id,'']]])
                await client.receive()
                # A delayed old report also cannot invalidate a newly joined
                # room on this same authenticated GS connection.
                for subtype in ('34','70'):await client.send(0xd1,[subtype,[roomid]])
                await client.send(0x3a)
                header,_=await client.receive();self.assertEqual(header.message_type,0x3a)
                self.assertEqual(len(registry.active_room(int(new_id),GR2.product).members),1)
                # No background watcher here: this incoming report discovers
                # expiry itself and invokes removal during active_room().
                state.unlink()
                await client.send(0xd1,['34',[new_id]])
                await client.send(0x3a)
                _,fields=await client.receive();self.assertEqual(fields,['55',[new_id]])
                header,_=await client.receive();self.assertEqual(header.message_type,0x3a)
            finally:
                client.writer.close();await client.writer.wait_closed()
                server.close();await server.wait_closed()
