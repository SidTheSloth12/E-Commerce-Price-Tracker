import requests
from bs4 import BeautifulSoup
api = '0482406ecec73d1c704201e552e44c04'
for asin in ['B0DRV5L8GC', 'B0FRGJWHJ7']:
    url = f'http://api.scraperapi.com?api_key={api}&url=https://www.amazon.in/dp/{asin}'
    r = requests.get(url, timeout=60)
    text = r.text
    print('===', asin, 'len', len(text), 'has 679', '₹679' in text)
    if '₹679' in text:
        idx = text.index('₹679')
        snippet = text[max(0, idx-120):idx+120]
        print(snippet)
    soup = BeautifulSoup(r.content, 'html.parser')
    nodes = soup.find_all(string=lambda s: '₹679' in s)
    print('nodes', len(nodes))
    for n in nodes[:10]:
        print('---- parent=', n.parent.name, 'attrs=', n.parent.attrs)
        print('text=', repr(n.strip()))
        print('parents=', [(p.name, p.get('id'), p.get('class')) for p in list(n.parents)[:10]])
PY
