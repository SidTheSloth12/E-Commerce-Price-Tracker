import requests
import re
headers={'User-Agent':'Mozilla/5.0'}
url='https://www.scraperapi.com/documentation/structured-apis'
r=requests.get(url, headers=headers, timeout=60)
print(r.status_code)
print('len',len(r.text))
for pat in ['amazon/product','structured/amazon','amazon_domain','domain=amazon','asin=','country_code=IN','structured-apis','structured api']:
    if pat in r.text:
        print('FOUND',pat)
for m in re.finditer('amazon', r.text):
    if m.start()<2000:
        print('first', r.text[m.start()-40:m.start()+120].replace('\n',' '))
        break
