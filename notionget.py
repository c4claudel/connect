from argparse import ArgumentParser
from pprint import pprint
import urllib.parse
import requests
import json
import re
import os

from notion_client import Client
from inlinestyler.utils import inline_css

NOTION_SECRET = os.environ.get('NOTION_SECRET')
OUTDIR = 'dist/'
IMAGES_PER_ARTICLE = 1
WORDS_PER_ARTICLE = 50
SITE_ROOT = 'https://connect.c4claudel.com/'
ARTICLE_SLUG_PLACEHOLDER = '--ARTICLE--SLUG--'

class NGet():
    def __init__(self):
        self._client = Client(auth=NOTION_SECRET)
    def pageInfo(self, pageid):
        return {
            'info': self._client.pages.retrieve(pageid),
            'blocks': list(self._fetchBlocksRecursively(pageid))
        }
    def _fetchBlocksRecursively(self, blockid):
        for block in self._fetchBlockChildren(blockid):
            block['children'] = list(self._fetchBlocksRecursively(block['id'])) \
                if block['has_children'] and not block['type']=='child_page' else None
            yield block
    def _fetchBlockChildren(self, blockid):
        some = None
        while not some or some['has_more']:
            print('FETCH BLOCKs')
            some = self._client.blocks.children.list(blockid, page_size=100, start_cursor=some['next_cursor'] if some else None)
            if some and 'results' in some:
                yield from some['results']
                more = some['has_more']
    def crawl(self, rootid, ):
        page = self.pageInfo(rootid)
        pages = [page]
        walkBlocks(page['blocks'],
                   lambda b,x: x.extend(self.crawl(b['id'])),
                   ['child_page'],
                   pages)
        return pages

def basename(url):
    name = url.split('?')[0].split('/')[-1]
    name = urllib.parse.unquote(name)
    return name.replace('unnamed_','resource_').replace('(','').replace(')','')
    
def cacheResource(blockid, resource, dest):
    url = resource[resource['type']]['url']
    outname = basename(url)
    if os.path.exists(dest+outname):
        print('CACHE OK', url , '->', outname)        
    else:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            print('CACHE', url , '->', outname, len(r.content),'B')
            with open(dest+outname,'wb') as f:
                f.write(r.content)
        else:
            print('CACHE OLD', url , '->', outname, r.status_code)
    return outname

def formatIcon(icon):
    if icon and icon['type']=='emoji': return icon['emoji']
    return ''

def formatText(snippets):
    def _span(snippet):
        txt = snippet['plain_text'].replace('\n','<br/>')
        snippet['annotations']['color'] = False #TODO color
        styles = ' '.join(['snippet-'+k for k,v in snippet['annotations'].items() if v])
        if styles: txt = '<span class="%s">%s</span>' % (styles, txt)
        return txt
    return ''.join(_span(t) for t in snippets)

def pageToHtml(page, urlmap, stylesheet):
    title = formatText(page['info']['properties']['title']['title'])
    html = '<html><head>' \
        + '<title>%s</title>' % htmlToText(title) \
        + '<link rel="stylesheet" href="%s">'  % stylesheet \
        + '</head><body>' \
        + '<div class="connect-page">' \
        + '<header class="connect-header">'
    cover = (page['info'].get('cover') or {}).get('external')
    if cover:
        html += '<img src="%s">' % urlmap[cover['url']]
    html += ' <h1>%s %s</h1>' % (formatIcon(page['info'].get('icon')), title) \
        + '</header><div class="connect-body">' \
        + blocksToHtml(page['blocks'], urlmap) \
        + '</div></div></body></html>'
    return html

def blocksToHtml(blocks, urlmap):
    return '\n'.join(blockToHtml(b, urlmap) for b in blocks)

def blockToHtml(block, urlmap):
    btype = block['type']
    i = block.get(btype) or {}
    OPS = {
        'child_page': lambda b: '<div class="connect-childpage"><a href="%s">%s%s</a></div>' % (urlmap[b['id']],formatIcon(i.get('icon')),i['title']),
        'heading_1': lambda b: '<h2><a name="%s"/>%s</h2>' % (textToSlug(formatText(i['text'])),formatText(i['text'])) if not i.get('link') \
                               else '<h2><a href="%s">%s</a></h2>'  % (i['link'],formatText(i['text'])),
        'paragraph': lambda b: '<div class="connect-paragraph">%s</div>' % formatText(i['text']),
        'divider': (lambda b: '<hr/>'),
        'image': (lambda b: '<figure><a href="%s"><img src="%s"/></a><figcaption>%s</figcaption></figure>' % (i.get('link') or '',urlmap[b['id']],i['caption'] or '')),
        'callout': (lambda b: '<div class="connect-callout"><div class="connect-callout-header"><span>%s</span><span>%s</span></div><div class="connect-callout-body">%s</div></div>' % (i['icon']['emoji'],formatText(i['text']),blocksToHtml(b['children'], urlmap))),
        'column': lambda b: '<div class="connect-column %s">%s</div>' % ('column-image' if b['children'][0]['type']=='image' else '', blocksToHtml(b['children'], urlmap)),
        'column_list': lambda b: '<div class="connect-column-list">%s</div>' % blocksToHtml(b['children'], urlmap),
        'bulleted_list_item': lambda b: '<div class="connect-bulleted-item">%s</div>' % formatText(i['text']),
        'table_of_contents': lambda b: '<div class="connect-toc">%s</div>' % \
                          '<br/>'.join('<a href="#%s">%s</a>' % (textToSlug(h),htmlToText(h)) for n,h in i['headings']),
        'embed': lambda b: '<iframe class="connect-embed" src="%s"></iframe>' % i['url'],
        'file': lambda b: '<a class="connect-file" href="%s" target="_blank">&#x1F4E6; %s</a>' % (urlmap[b['id']], basename(i['file']['url'])),
        # summarizing
        '_drop_': lambda b: '',
        '_hoist_': lambda b: blocksToHtml(b['children'], urlmap),
        '_default': (lambda b: '<!-- UNKNOWN %r -->' % b),
    }
    op = OPS.get(btype) or OPS.get('_default')
    return op(block)        

def walkBlocks(blocks, op, btypes=None, *args):
    for b in blocks:
        if not btypes or b['type'] in btypes:
            op(b, *args)
        if b['children']:
            walkBlocks(b['children'], op, btypes, *args)

def textToSlug(text):
    return re.sub('[^a-zA-Z0-9]','-',htmlToText(text).lower())

def htmlToText(html):
    return re.sub('<.*?>','',html)

def preprocesAndCachePage(p):
    urlmap = {}
    slug = textToSlug(formatText(p['info']['properties']['title']['title']))
    while slug in urlmap.values(): slug += '-1'
    urlmap[p['info']['id']] = slug + '.html'

    #TODO cache images and other files
    cover = (p['info'].get('cover') or {}).get('external')
    print('COVER:', cover)
    if cover: urlmap[cover['url']] = cacheResource(p['info']['id']+'-cover', p['info'].get('cover'), OUTDIR)
    walkBlocks(p['blocks'],
               lambda b: urlmap.update({b['id']: cacheResource(b['id'], b[b['type']], OUTDIR)}),
               ['image','file'])

    headings = []
    walkBlocks(p['blocks'],
               lambda b,h: h.append((1,formatText(b['heading_1']['text']))),
               ['heading_1'], headings)
    print('HEADERS',headings)

    walkBlocks(p['blocks'],
               lambda b: b.update({'table_of_contents': {'headings': headings}}),
               ['table_of_contents'])
    return urlmap

def summarizePage(page, site):
    articles = [[]]
    currentArticle = None
    ptitle = page['info']['properties']['title']['title'][0]['plain_text']

    for block in page['blocks']:
        if block['type'] == 'heading_1' or (len(articles)>1 and block['type']=='callout'):
            block.get('heading_1',{})['link'] = ARTICLE_SLUG_PLACEHOLDER
            articles.append([block])
        else:
            articles[-1].append(block)
            
    def trimSummary(block, counts):
        if block['type'] == 'image':
            block['image']['link'] = ARTICLE_SLUG_PLACEHOLDER
            if counts['nimg'] <= 0:
                block['type'] = '_drop_'
            counts['nimg'] -= 1
        elif block['type'] == 'paragraph':
            if counts['ntxt'] <= 0:
                block['type'] = '_drop_'
            wc = len(htmlToText(formatText(block['paragraph']['text'])).split())
            counts['ntxt'] -= wc
        elif block['type'] == 'callout': #keep all
            if block['children'][0]['type'] == 'table_of_contents': #except toc
                block['type'] = '_drop_'
            else:
                print('KEEP', counts)
                counts['ntxt'] += 10000
                counts['nimg'] += 10
        elif block['type'] in ['column_list', 'column']: #hoist children
            block['type'] = '_hoist_'                    
        
    for ar in articles:
        counts = {'nimg': IMAGES_PER_ARTICLE, 'ntxt': WORDS_PER_ARTICLE}
        atitle = ar[0].get('heading_1',{}).get('text',[{}])[-1].get('plain_text','?')
        print('SUMMARIZE', ptitle, atitle)
        walkBlocks(ar, trimSummary, None, counts)
        # move images to the front
        SUMSORT = { 'heading_1': 1, 'image': 2, '_hoist_': 3 }
        ar.sort(key=lambda b: SUMSORT.get(b['type'],100))
        # flag if trimmed
        ar.insert(0, counts['nimg'] < 0 or counts['ntxt'] < 0)
        print('SUMMARIZED', counts, ar[0], ptitle, atitle, [b['type'] for b in ar[1:]])
        
    return articles
    
if __name__ == '__main__':
    Options = ArgumentParser(description='Newsletter Publisher')
    Options.add_argument('--fetch', action='store_true')
    Options.add_argument('files', type=str, nargs='+')
    opts = Options.parse_args()

    nget = NGet()

    rootid = opts.files[0].split('-')[-1]
    cachefile = rootid + '-cache.json'
    print('ROOT is:', rootid)

    if opts.fetch:
        pages = nget.crawl(rootid)
        with open(cachefile,'wt') as f: f.write(json.dumps(pages))
    else:
        with open(cachefile,'rt') as f: pages = json.loads(f.read())

    # preprocess: rewrite URLs and cache resources
    urlmap = {}
    for p in pages:
        urlmap.update(preprocesAndCachePage(p))        

    #pprint(urlmap)
    for p in pages:
        html = pageToHtml(p, urlmap, '../resources/connect.css')
        slug = urlmap[p['info']['id']]
        with open(OUTDIR+slug,'wt') as f:
            f.write(html)

    for p in pages:
        articles = summarizePage(p, 'https://connect.c4claudel.com')
        html = '<div class="connect-mail"><style>%s</style>' % open('resources/connect.css','rt').read()
        for i,ar in enumerate(articles):
            more = '<a href="%s">Continue...</a>' % ARTICLE_SLUG_PLACEHOLDER if ar.pop(0) else ''
            html += '<div class="connect-%s">%s%s</div>' % ('lead' if i==0 else 'article', blocksToHtml(ar, urlmap), more)
            dest = textToSlug(formatText(ar[0].get('heading_1',{}).get('text',[])))
            html = html.replace(ARTICLE_SLUG_PLACEHOLDER, dest)
            
        html += '</div>'
        
        mailablemsg = inline_css(html)

        slug = urlmap[p['info']['id']]
        with open(OUTDIR+slug+'.summary.html','wt') as f:
            f.write(mailablemsg)
    
    #page = nget.pageInfo('9ca6b166f315435786896f072471c888')
    #pprint(page)
    #print(len(page['blocks']))
    #print(pageToHtml(page))
    #walkBlocks(page['blocks'],
    #           lambda b: print('IMAGE', b['image']['url']),
    #           ['image'])
    #walkBlocks(page['blocks'],
    #           lambda b: print('CHILD', b['child_page']),
    #           ['child_page'])
    #
    #print(nget.crawl('9ca6b166f315435786896f072471c888'))
