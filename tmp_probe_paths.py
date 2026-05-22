import requests
key='0482406ecec73d1c704201e552e44c04'
paths=[
 'https://api.scraperapi.com/structured/amazon/product',
 'https://api.scraperapi.com/structured/amazon/product/',
 'https://api.scraperapi.com/structured/amazon',
 'https://api.scraperapi.com/structured/amazon/',
 'https://api.scraperapi.com/structured/amazon_product',
 'https://api.scraperapi.com/structured/product/amazon',
 'https://api.scraperapi.com/structured/amazon.com/product',
 'https://api.scraperapi.com/structured/amazonin/product',
 'https://api.scraperapi.com/structured/amazon/product.json',
 'https://api.scraperapi.com/v1/structured/amazon/product',
 'https://api.scraperapi.com/v1/structured/amazon',
 'https://api.scraperapi.com/amazon/structured/product',
 'https://api.scraperapi.com/amazon/structured',
 'https://api.scraperapi.com/structured',
 'https://api.scraperapi.com/structured/',
]
for base in paths:
    try:
        r=requests.get(base, timeout=30)
        print('BASE', base, 'status', r.status_code)
        print('text', r.text[:240])
    except Exception as e:
        print('BASE', base, 'ERROR', e)
    print('---')
