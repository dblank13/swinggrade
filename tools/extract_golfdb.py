import sys, json
from scipy.io import loadmat
x = loadmat(sys.argv[1])
rows=[]
for r in x['golfDB'][0]:
    ev=[int(v) for v in r[7][0]]
    rows.append(dict(id=int(r[0][0][0]), youtube_id=str(r[1][0]), player=str(r[2][0]), sex=str(r[3][0]),
        club=str(r[4][0]), view=str(r[5][0]), slow=int(r[6][0][0]), events=ev, bbox=[float(v) for v in r[8][0]]))
json.dump(rows, open(sys.argv[2],'w'))
print(len(rows), len({r['player'] for r in rows}), len({r['youtube_id'] for r in rows}))
from collections import Counter
print(Counter(r['view'] for r in rows)); print(Counter(r['club'] for r in rows)); print(rows[0])
print(Counter(r['player'] for r in rows).most_common(12))
