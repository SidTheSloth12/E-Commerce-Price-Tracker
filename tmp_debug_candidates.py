import requests
from bs4 import BeautifulSoup
import re
api = '0482406ecec73d1c704201e552e44c04'
for asin in ['B0FRGJWHJ7', 'B0DRV5L8GC']:
    url = f'http://api.scraperapi.com?api_key={api}&url=https://www.amazon.in/dp/{asin}'
    r = requests.get(url, timeout=60)
    print('===', asin, 'status', r.status_code)
    soup = BeautifulSoup(r.content, 'html.parser')
    if soup.select_one('#corePrice_feature_div span.a-offscreen'):
        print('coreprice exists')
    print('productTitle exists', bool(soup.select_one('#productTitle')))
    print('availability', [d.get_text(' ', strip=True) for d in soup.select('#availability, #outOfStock')])
    buyers = soup.select('#price_inside_buybox, #newBuyBoxPrice, .apexPriceToPay span.a-offscreen, #buybox span.a-offscreen')
    print('buybox len', len(buyers), [b.get_text(strip=True) for b in buyers])
    candidates = []
    for n in soup.select('#corePrice_feature_div span.a-offscreen'):
        candidates.append(n)
    for n in soup.select('#priceblock_ourprice, #priceblock_dealprice, #priceblock_saleprice, #priceblock_pospromo'):
        candidates.append(n)
    for n in soup.select('#price_inside_buybox, #newBuyBoxPrice, .apexPriceToPay span.a-offscreen, #buybox span.a-offscreen'):
        candidates.append(n)
    for n in soup.select('span.a-price span.a-offscreen'):
        candidates.append(n)
    for n in soup.select('span.a-price-whole'):
        candidates.append(n)
    print('candidate count', len(candidates))
    def score(node):
        if not node:
            return -999
        score = 0
        if node.find_parent(id='corePrice_feature_div'):
            score += 100
        if node.find_parent(id='price_inside_buybox'):
            score += 90
        if node.find_parent(id='newBuyBoxPrice'):
            score += 90
        ancestor = node.find_parent(attrs={'data-asin': True})
        if ancestor and ancestor.get('data-asin') and ancestor.get('data-asin').strip().lower() == asin.lower():
            score += 80
        if node.find_parent('a'):
            score -= 50
        for ancestor in node.parents:
            aid = ancestor.get('id') or ''
            if aid.startswith('CardInstance') or aid.startswith('sims-') or aid.startswith('sp_detail2'):
                score -= 30
                break
        product_title_node = soup.select_one('#productTitle')
        if product_title_node:
            n = node
            for _ in range(6):
                n = n.parent
                if not n:
                    break
                if product_title_node in n.descendants:
                    score += 30
                    break
        txt = node.get_text(strip=True) if node and node.get_text else ''
        if re.search(r'\d', txt):
            score += 5
        return score
    scored = [(score(n), n.get_text(strip=True), n.name, [p.get('id') for p in n.parents if p.get('id')][:3], bool(n.find_parent('a'))) for n in candidates]
    scored.sort(reverse=True, key=lambda x: x[0])
    for s, t, name, parent_ids, in_a in scored[:20]:
        print('score', s, 'text', repr(t), 'name', name, 'parent_ids', parent_ids, 'in_a', in_a)
    print('---')
