import requests
key='0482406ecec73d1c704201e552e44c04'
base='https://api.scraperapi.com/structured/amazon/product'
options=[
    {'api_key':key,'url':'https://www.amazon.in/dp/B0DRV5L8GC','country_code':'IN'},
    {'api_key':key,'url':'https://www.amazon.in/dp/B0DRV5L8GC','amazon_domain':'amazon.in'},
    {'api_key':key,'asin':'B0DRV5L8GC','amazon_domain':'amazon.in'},
    {'api_key':key,'asin':'B0DRV5L8GC','domain':'amazon.in'},
    {'api_key':key,'asin':'B0DRV5L8GC','amazon_domain':'amazon.co.in'},
    {'api_key':key,'asin':'B0DRV5L8GC','amazon_domain':'in'},
]
for params in options:
    r=requests.get(base, params=params, timeout=60)
    print('PARAMS', params)
    print('URL', r.url)
    print('status', r.status_code)
    print('text', r.text[:400])
    print('---')
