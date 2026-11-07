"""Opt-in GR2 named-player ranking tables over shared raw statistics.

Original table/column contract: 4f4fd0, 406130, 4057c0, 4071e0..4073e0.
Tubisoft policy: SCORE is team wins; GRADE remains zero (no recovered skill
formula). COUNTRY/COUNTRY_ID are empty/zero, with no geolocation or country data.
Only the observed named-alias selector 4 is implemented; other selections keep
their original empty-success path until their semantics are verified.
"""
from .gr2 import GR2Profile
from ..ladder import LadderStore

COLUMNS=(('GLOBAL_RANK','integer'),('ALIAS','string'),('COUNTRY','string'),('COUNTRY_ID','integer'),
         ('GRADE','integer'),('SCORE','integer'),('KILL','integer'),('TEAMKILL','integer'),('DEATH','integer'))
MODES={0:None,1:'assault',2:'sabotage',3:'onslaught',4:'team-survival'}


def ranking_table(profile,fields,username,store):
    # Reuse the title adapter's exact product/version/query validation.
    empty=profile.ranking_table(fields,username)
    if not isinstance(profile,GR2Profile)or not isinstance(store,LadderStore):raise ValueError('Matching GR2 ranking store required')
    query=fields[1];selection=query[4]
    if selection[0]!='4' or query[5][1] or query[5][2]:return empty
    aliases=selection[1]
    if len(aliases)>100 or any(not isinstance(a,str)or not 1<=len(a)<=128 for a in aliases):raise ValueError('Bounded alias selection required')
    columns=query[5][0]
    if any(not isinstance(c,str)or c not in dict(COLUMNS)for c in columns):return empty
    rows=[];seen=set()
    for alias in aliases:
        if alias.casefold()in seen:continue
        seen.add(alias.casefold())
        record=store.account_statistics(alias,profile.product,mode=MODES[int(query[3])])
        if record is None:continue
        values=(record['rank'],record['name'],'',0,0,record['team_wins'],record['kills'],record['team_kills'],record['deaths'])
        if any(type(v)is int and not 0<=v<=0x7fffffff for v in values):continue
        rows.append([str(v)for v in values])
    if not rows:return empty
    return ['1',[query[0],str(len(rows)),[list(c)for c in COLUMNS],rows]]
