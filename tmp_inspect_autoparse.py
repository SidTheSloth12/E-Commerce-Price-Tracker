import requests, json
key='0482406ecec73d1c704201e552e44c04'
for asin in ['B0DRV5L8GC','B0FRGJWHJ7','B0GJ4724L4','B0F92RNPYF']:
    url=f'http://api.scraperapi.com?api_key={key}&url=https://www.amazon.in/dp/{asin}&country_code=IN&autoparse=1'
    r=requests.get(url, timeout=60)
    print('===', asin, 'status', r.status_code)
    data=r.json()
    print('top keys', list(data.keys()))
    for k,v in data.items():
        if isinstance(v, dict):
            print('  dict', k, list(v.keys())[:20])
        elif isinstance(v, list):
            print('  list', k, len(v), 'sample type', type(v[0]).__name__ if v else None)
        else:
            print('  scalar', k, repr(v)[:200])
    print('---')
