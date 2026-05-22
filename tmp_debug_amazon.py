import requests
from bs4 import BeautifulSoup
api = '0482406ecec73d1c704201e552e44c04'
for asin in ['B0FRGJWHJ7', 'B0DRV5L8GC']:
    url = f'http://api.scraperapi.com?api_key={api}&url=https://www.amazon.in/dp/{asin}'
    r = requests.get(url, timeout=60)
    print('===', asin, 'status', r.status_code)
    soup = BeautifulSoup(r.content, 'html.parser')
    print('title:', soup.title.string if soup.title else None)
    print('productTitle:', bool(soup.select_one('#productTitle')))
    print('ASIN input:', [i.get('value') for i in soup.select('input#ASIN,input[name=ASIN]')])
    print('canonical:', bool(soup.select_one('link[rel="canonical"]')))
    print('availability:', [d.get_text(' ', strip=True) for d in soup.select('#availability, #outOfStock')])
    print('corePrice:', [x.get_text(' ', strip=True) for x in soup.select('#corePrice_feature_div span.a-offscreen')])
    print('buybox:', [x.get_text(' ', strip=True) for x in soup.select('#price_inside_buybox, #newBuyBoxPrice, .apexPriceToPay span.a-offscreen, #buybox span.a-offscreen')])
    print('priceblock:', [x.get_text(' ', strip=True) for x in soup.select('#priceblock_ourprice, #priceblock_dealprice, #priceblock_saleprice, #priceblock_pospromo')])
    print('a-price offscreen count:', len(soup.select('span.a-price span.a-offscreen')))
    print('---')
