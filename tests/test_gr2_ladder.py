import copy,tempfile,unittest
from pathlib import Path
from ubisoft.accounts import create_account
from ubisoft.ladder import LadderStore
from ubisoft.games.gr2_ladder import COLUMNS
from ubisoft.games.registry import GR2,XIII
from ubisoft import proxy,data
from ubisoft.service import configuration
from test_ladder import report
from test_proxy import query


class NativeLadderTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'accounts.sqlite3'
        for name in('First','Second'):create_account(self.path,name,'fixture-password')
        self.store=LadderStore(self.path);self.store.record(report())

    def request(self,*,ladder='1',aliases=None):
        value=query();value[2][1][3]=ladder
        value[2][1][4][1]=['FIRST','Second','first','unknown']if aliases is None else aliases
        return value

    def test_native_table_preserves_both_ids_metadata_and_string_cells(self):
        reply=proxy.query_reply(GR2,self.request(),'First',ranking_store=self.store)
        self.assertEqual(data.decode(data.encode(reply)),reply)
        self.assertEqual(reply[:2],['1281','17'])
        table=reply[2][1];self.assertEqual(table[0],'1')
        app_id,total,columns,rows=table[1]
        self.assertEqual((app_id,total),('900','2'))
        self.assertEqual(columns,[list(v)for v in COLUMNS])
        self.assertEqual(rows[0],['1','First','','0','0','1','3','0','1'])
        self.assertEqual(rows[1],['2','Second','','0','0','0','1','0','1'])

    def test_ladder_scopes_and_default_unranked_reply_remain_separate(self):
        self.assertEqual(proxy.query_reply(GR2,self.request(),'First')[2][1],['1',['900','0',[],[]]])
        for ladder in('2','3','4'):
            self.assertEqual(proxy.query_reply(GR2,self.request(ladder=ladder),'First',ranking_store=self.store)[2][1],['1',['900','0',[],[]]])
        self.store.record(report(mode='sabotage',round=2))
        overall=proxy.query_reply(GR2,self.request(ladder='0'),'First',ranking_store=self.store)
        self.assertEqual(overall[2][1][1][3][0][5:7],['2','6'])
        other=report(product=XIII.product,mode='deathmatch',round=3);self.store.record(other)
        self.assertEqual(proxy.query_reply(GR2,self.request(ladder='0'),'First',ranking_store=self.store),overall)

    def test_unknown_selection_sort_or_column_keeps_empty_success(self):
        for part,value in((4,['0',['1','10']]),(5,[['NOT_A_COLUMN'],[],[]]),(5,[[],['SCORE'],[]]),(5,[[],[],['opaque-filter']])):
            request=self.request();request[2][1][part]=value
            self.assertEqual(proxy.query_reply(GR2,request,'First',ranking_store=self.store)[2][1],['1',['900','0',[],[]]])
        with self.assertRaises(ValueError):proxy.query_reply(GR2,self.request(aliases=['First']*101),'First',ranking_store=self.store)
        self.assertEqual(proxy.query_reply(GR2,self.request(aliases=['unknown']),'First',ranking_store=self.store)[2][1],['1',['900','0',[],[]]])

    def test_empty_defaults_and_paired_private_results_configuration(self):
        base={'TUBISOFT_ADVERTISE_IP':'192.0.2.10'};args=configuration(base)
        self.assertIsNone(args.results_keyring);self.assertFalse(args.native_rankings)
        for extra in({'TUBISOFT_RESULTS_PORT':'8081'},{'TUBISOFT_RESULTS_KEYRING':'private-keyring.json'}):
            with self.assertRaises(ValueError):configuration(base|extra)
        args=configuration(base|{'TUBISOFT_RESULTS_PORT':'8081','TUBISOFT_RESULTS_KEYRING':'private-keyring.json','TUBISOFT_NATIVE_RANKINGS':'1'})
        self.assertTrue(args.native_rankings);self.assertEqual(args.results_keyring,Path('private-keyring.json'))
