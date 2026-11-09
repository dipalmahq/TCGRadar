"""Detail refresh must retain fresh category evidence, excluding global menus."""
import json

import pytest

from app.adapters.base import ShopClient
from app.adapters.structured_html import StructuredHtmlAdapter
from app.domain import classify


@pytest.mark.parametrize('markup', ['html', 'json'])
@pytest.mark.parametrize('title,path,expected', [
    ('Marshadow Kollektion', ['Startseite', 'Pokemon Karten'], 'pokemon'),
    ('Sun & Moon GG End SM10a Display Japanisch', ['Pokemon Karten'], 'pokemon'),
    ('Riftbound Display', ['Pokemon Karten'], None),
    ('Marshadow 082/198 PSA 10 Collection', ['Pokemon Karten'], None),
    ('Marshadow Kollektion', [], None),
    ('Marshadow Kollektion', ['Pokemon Karten', 'One Piece'], None),
])
def test_detail_uses_only_unambiguous_product_breadcrumb(settings, markup, title, path, expected):
    product={'@type':'Product','name':title,'offers':{'@type':'Offer','url':'https://fixture.example/test',
             'price':'99.00','priceCurrency':'EUR','availability':'https://schema.org/InStock'}}
    page='<nav><a>Pokemon Karten</a><a>One Piece</a></nav>'
    page+='<script type="application/ld+json">'+json.dumps(product)+'</script>'
    if markup=='html':
        page+='<ol class="breadcrumb">'+''.join('<li><a>'+name+'</a></li>' for name in path)+'</ol>'
    else:
        page+='<script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'BreadcrumbList',
              'itemListElement':[{'@type':'ListItem','position':i+1,'name':name} for i,name in enumerate(path)]}]})+'</script>'
    client=ShopClient('https://fixture.example',settings)
    try:
        item,=StructuredHtmlAdapter(client,{}).parse(page,'https://fixture.example/test',True)
        result=classify(item,'fixture')
        assert (result.game if result else None)==expected
    finally:client.close()
