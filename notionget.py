from argparse import ArgumentParser
from pprint import pprint
from dateutil.parser import isoparse
import urllib.parse
import datetime
import requests
import json
import re
import os

from notion_client import Client
from inlinestyler.utils import inline_css

NOTION_SECRET = os.environ.get('NOTION_SECRET')
OUTDIR = 'docs/'
IMAGES_PER_ARTICLE = 1
WORDS_PER_ARTICLE = 75
WORDS_PER_ARTICLE_EXCESS = 25
SITE_ROOT = 'https://connect.c4claudel.com/'
ARTICLE_SLUG_PLACEHOLDER = '--ARTICLE--SLUG--'
SUMMARY_READMORE_PLACEHOLDER = '--READ-MORE--'

class NGet():
    def __init__(self):
        if not NOTION_SECRET:
            raise(Exception("no notion secret token. please set NOTION_SECRET"))
        self._client = Client(auth=NOTION_SECRET)
    def fetchPage(self, pageid):
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
    def crawl(self, rootid, dateLimit):
        page = self.fetchPage(rootid)
        pages = [page]
        crawled = []
        done = False
        while not done:
            done = True
            subpages = []
            def crawlSub(blk, parent):
                if blk in subpages: return
                if isoparse(blk['last_edited_time']).date() < dateLimit: return
                parentTitle = parent['info']['properties']['title']['title']
                print('CRAWL Page ',parentTitle[0]['plain_text'],'->',blk['child_page']['title'])
                page = self.fetchPage(blk['id'])
                page['parent'] = { 'id': parent['info']['id'], 'title': parentTitle }
                subpages.append(page)
            for page in pages:
                if not page in crawled:
                    crawled.append(page)
                    walkBlocks(page['blocks'], crawlSub, ['child_page'], page)
            if subpages:
                pages.extend(subpages)
            done = not subpages
            print('CRAWLED', done)
        return pages

def basename(url):
    name = url.split('?')[0].split('/')[-1]
    name = urllib.parse.unquote(name)
    return name.replace('unnamed_','resource_').replace('(','').replace(')','')
    
def cacheResource(blockid, resource, dest):
    url = resource[resource['type']]['url']
    outname = blockid+'-'+basename(url)
    extension = outname.split('.')[-1][:4].lower()
    fullpath = dest+outname
    if os.path.exists(fullpath):
        print('CACHE OK', url , '->', outname)        
    else:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            print('CACHE', url , '->', outname, len(r.content),'B')
            with open(fullpath,'wb') as f:
                f.write(r.content)
    if extension in ['jpg','jpeg','png','gif']:
        #downscaled versions
        for dim in [1024]:
            downfile = outname.replace('.'+extension,'-s%d.%s' % (dim, extension))
            downpath = dest + downfile
            if not os.path.exists(downpath):
                os.system('convert %s -geometry %dx%d %s'
                          % (fullpath,dim,dim,downpath))
            outname = downfile
    return outname

def formatIcon(icon):
    if icon and icon['type']=='emoji': return icon['emoji']
    return ''

def formatText(snippets):
    def _span(snippet):
        txt = snippet['plain_text'].replace('\n','<br/>')
        snippet['annotations']['color'] = False #TODO color
        styles = ' '.join(['snippet-'+k for k,v in snippet['annotations'].items() if v])
        href = (snippet.get('text',{}).get('link') or {}).get('url')
        if href: txt = '<a href="%s" target="_blank" class="%s">%s</a>' % (href, styles, txt)
        elif styles: txt = '<span class="%s">%s</span>' % (styles, txt)
        return txt
    return ''.join(_span(t) for t in snippets or [])

RE_YoutubeEmbed = re.compile('https*://.*youtube.*/embed/([^?]+)')
RE_YoutubeWatch = re.compile('https*://.*youtube.*/watch\?v=([^&]+)')
def extractYouTubeId(url):
    match = RE_YoutubeWatch.match(url) or RE_YoutubeEmbed.match(url)
    print( 'YOUTUBE check', url, match)
    if match: return match[1]
    
def formatBlockText(block):
    #api is confused between rich_text and text
    content = block.get(block.get('type','xx'),{})
    return formatText(content.get('rich_text') or content.get('text'))

def pageToHtml(page, urlmap, stylesheet):
    title = formatText(page['info']['properties']['title']['title'])
    html = '<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">' \
        + '<title>%s</title>' % htmlToText(title) \
        + '<link rel="stylesheet" href="%s">'  % stylesheet \
        + '</head><body>' \
        + '<div class="connect-page">' \
        + '<header class="connect-header">'
    cover = (page['info'].get('cover') or {}).get('external')
    if cover:
        html += '<img src="%s">' % urlmap[cover['url']]
    #if 'parent' in page:
    #    html += '<div class="connect-breadcrumb"><a href="%s">&lt;&lt;<span class="connect-parent-title">%s</span></a></div>' \
    #        % (urlmap[page['parent']['id']], formatText(page['parent']['title']))
    html += ' <h1>%s %s</h1>' % (formatIcon(page['info'].get('icon')), title) \
        + '</header><div class="connect-body">' \
        + blocksToHtml(page['blocks'], urlmap) \
        + '</div></header></body></html>'
    return html

def blocksToHtml(blocks, urlmap):
    return '\n'.join(blockToHtml(b, urlmap) for b in blocks or [])

def blockToHtml(block, urlmap):
    btype = block['type']
    i = block.get(btype) or {}
    ftext = formatBlockText(block)
    OPS = {
        'child_page': lambda b: '<div class="connect-childpage"><a href="%s">%s%s</a></div>' % (urlmap[b['id']],formatIcon(i.get('icon')),i['title']),
        'heading_1': lambda b: '<h2><a name="%s"></a>%s</h2>' % (textToSlug(ftext),ftext) if not i.get('link') \
                               else '<h2><a href="%s">%s</a></h2>'  % (i['link'],ftext),
        'heading_2': lambda b: '<h3><a name="%s"></a>%s</h3>' % (textToSlug(ftext),ftext) if not i.get('link') \
                               else '<h3><a href="%s">%s</a></h3>'  % (i['link'],ftext),
        'paragraph': lambda b: '<div class="connect-paragraph">%s</div>' % ftext,
        'divider': (lambda b: '<hr/>'),
        'image': (lambda b: '<div class="connect-figure"><a href="%s" target="_blank"><img src="%s"/></a><div class="connect-caption">%s</div></div>' % (i.get('link') or urlmap[b['id']],urlmap[b['id']],formatText(i['caption']) if i['caption'] else '')),
        'callout': (lambda b: '<div class="connect-callout"><div class="connect-callout-header"><span>%s</span><span>%s</span></div><div class="connect-callout-body">%s</div><div class="connect-callout-footer"></div></div>' % (i['icon']['emoji'],ftext,blocksToHtml(b['children'], urlmap))),
        'link_to_page': lambda b: '<a href="%s">%s</a>' % (i['page_id'],i['page_id']),
        'column': lambda b: '<div class="connect-column %s">%s</div>' % ('column-image' if b['children'][0]['type']=='image' else '', blocksToHtml(b['children'], urlmap)),
        'column_list': lambda b: '<div class="connect-column-list">%s</div>' % blocksToHtml(b['children'], urlmap),
        'bulleted_list_item': lambda b: '<div class="connect-bulleted-item">%s</div>' % ftext,
        'numbered_list_item': lambda b: '<div class="connect-numbered-item">%s</div>' % ftext,
        'table_of_contents': lambda b: '<div class="connect-toc">%s</div>' % \
        '<br/>'.join('<a href="#%s">%s</a>' % (textToSlug(h),htmlToText(h)) for n,h in i['headings']),
        'embed': lambda b: '<iframe class="connect-embed" src="%s"></iframe>' % i['url'],
        'video': lambda b: '<iframe width="560" height="315" src="https://www.youtube.com/embed/%s" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>' % extractYouTubeId(i['external']['url']),
        'file': lambda b: '<a class="connect-file" href="%s" target="_blank"e>&#x1F4E6; %s</a>' % (urlmap[b['id']], basename(i['file']['url'])),
        # summarizing
        '_drop_': lambda b: '',
        '_hoist_': lambda b: blocksToHtml(b['children'], urlmap),
        '_default': (lambda b: '<!-- UNKNOWN %r -->' % b),
        '_thumb': lambda b: '<div class="connect-figure"><a href="%s" target="_blank"><img src="%s"/></a></div>'\
                   % (i.get('link') or urlmap[b['id']], i.get('src') or urlmap[b['id']]),
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
    if cover:
        urlmap[cover['url']] = cacheResource(p['info']['id']+'-cover', p['info'].get('cover'), OUTDIR)
    walkBlocks(p['blocks'],
               lambda b: urlmap.update({b['id']: cacheResource(b['id'], b[b['type']], OUTDIR)}),
               ['image','file'])

    #build ToC
    headings = []
    walkBlocks(p['blocks'],
               lambda b,h: h.append((1,formatBlockText(b))),
               ['heading_1'], headings)
    print('HEADERS',headings)

    walkBlocks(p['blocks'],
               lambda b: b.update({'table_of_contents': {'headings': headings}}),
               ['table_of_contents'])
    return urlmap

def summarizePage(page):
    articles = [[]]
    currentArticle = None
    ptitle = page['info']['properties']['title']['title'][0]['plain_text']

    for block in page['blocks']:
        if block['type'] == 'heading_1' or (len(articles)>1 and block['type']=='callout'):
            block.get('heading_1',{})['link'] = ARTICLE_SLUG_PLACEHOLDER
            articles.append([block])
        else:
            articles[-1].append(block)

    def wordCount(block):
        return len(htmlToText(formatBlockText(block)).split())
        
    def trimBlockText(block, limit):
        content = block.get(block['type'],{})
        text = content.get('rich_text') or content.get('text')
        while wordCount(block) > limit:
            excess = wordCount(block) - limit
            tail = text[-1]
            words = tail['plain_text'].split()
            print('TRIMTEXT', excess, 'of', len(words),'/',wordCount(block))
            if len(words) <= excess:
                text.pop()
            else:
                tail['plain_text'] = ' '.join(words[:-excess-1]) + '... ' + SUMMARY_READMORE_PLACEHOLDER
    
    def trimSummary(block, counts):
        print('TRIM?', block['type'])
        if block['type'] == 'image':
            block['image']['link'] = ARTICLE_SLUG_PLACEHOLDER
            if counts['nimg'] <= 0:
                block['type'] = '_drop_'
            counts['nimg'] -= 1
        elif counts['nimg'] > 0 and block['type'] == 'video' and block['video']['type'] == 'external':
            block['type'] = '_thumb'
            block['_thumb'] = { 'link': ARTICLE_SLUG_PLACEHOLDER,
                                'src': 'https://img.youtube.com/vi/%s/hqdefault.jpg'
                                % extractYouTubeId(block['video']['external']['url']) }
            counts['nimg'] -= 1
        elif block['type'] in ['paragraph', 'bulleted_list_item', 'numbered_list_item']:
            wc = wordCount(block)
            if counts['ntxt'] <= 0:
                print('TRIM DROP', block['type'])
                block['type'] = '_drop_'
                counts['ntxt'] -= wc #extra paras are dropped
            elif counts['ntxt'] >= wc:
                print('TRIM KEEP', block['type'])
                counts['ntxt'] -= wc
            elif wc - counts['ntxt'] < WORDS_PER_ARTICLE_EXCESS:
                print('TRIM CONC', block['type'])
                counts['ntxt'] = 0 #concede the whole paragraph
            else:
                print('TRIM HALF', block['type'])
                trimBlockText(block, counts['ntxt']) 
                counts['ntxt'] -= wc #trim inside paragraph                                
        elif block['type'] == 'callout': #keep all
            if block['children'] and block['children'][0]['type'] == 'table_of_contents': #except toc
                block['type'] = '_drop_'
                block['children'][0]['type'] = '_drop_'
            else:
                print('KEEP', counts)
                counts['ntxt'] += 10000
                counts['nimg'] += 10
        elif block['type'] in ['column_list', 'column']: #hoist children
            block['type'] = '_hoist_'                    

    def flattenBlocks(block, flattened):
        if block['type'] != '_hoist_':
            flattened.append(block)
        
    for i,ar in enumerate(articles):
        counts = {'nimg': IMAGES_PER_ARTICLE, 'ntxt': WORDS_PER_ARTICLE * (10 if i==0 else 1)}        
        atitle = htmlToText(formatBlockText(ar[0]))
        print('SUMMARIZE', ptitle, atitle)
        
        walkBlocks(ar, trimSummary, None, counts)

        # hoist child blocks
        flattened = []
        walkBlocks(ar, flattenBlocks, None, flattened)
        ar.clear()
        ar.extend(flattened)
        
        # move images to the front
        SUMSORT = { 'heading_1': 1, 'image': 2, '_thumb': 2 } #?? , '_hoist_': 3 }
        ar.sort(key=lambda b: SUMSORT.get(b['type'],100))
        # flag if trimmed
        ar.insert(0, counts['nimg'] < 0 or counts['ntxt'] < 0)
        print('SUMMARIZED', counts, ar[0], ptitle, atitle, [b['type'] for b in ar[1:]])
        
    return articles
    
if __name__ == '__main__':
    Options = ArgumentParser(description='Newsletter Publisher')
    Options.add_argument('--fetch', action='store_true')
    Options.add_argument('--since', type=int)
    Options.add_argument('files', type=str, nargs='+')
    opts = Options.parse_args()

    nget = NGet()

    rootid = opts.files[0].split('-')[-1]
    cachefile = rootid + '-cache.json'
    print('ROOT is:', rootid)

    try:
        with open(cachefile,'rt') as f:
            pages = json.loads(f.read())
    except:
        pages = []
    
    dateLimit = datetime.date.today() - datetime.timedelta(opts.since or 9999)
    print("DATE LIMIT:", dateLimit)
    
    for p in pages:
        title = p['info']['properties']['title']['title'][0]['text']
        date = isoparse(p['info']['last_edited_time']).date()
        if date < dateLimit:
            print("SKIP:", title, date)
        else:
            print("DROP:", title, date)
    
    if opts.fetch:
        newpages = nget.crawl(rootid, dateLimit)
        if opts.since:
            print("OLD_PAGES", len(pages))
            print("NEW_PAGES", len(newpages))
            for np in newpages:
                pages = [p for p in pages if p['info']['id'] != np['info']['id']] + [np]
            print("COMBINED_PAGES", len(pages))
        else:
            pages = newpages
        with open(cachefile,'wt') as f: f.write(json.dumps(pages))

    for p in pages:
        title = p['info']['properties']['title']['title'][0]['text']
        date = isoparse(p['info']['last_edited_time']).date()
        print("PAGE:", title, date)
            
    # preprocess: rewrite URLs and cache resources
    urlmap = {}
    for p in pages:
        urlmap.update(preprocesAndCachePage(p))        

    #pprint(urlmap)
    for p in pages:
        
        # output full version
        html = pageToHtml(p, urlmap, 'connect.css')
        slug = urlmap[p['info']['id']]
        with open(OUTDIR+slug,'wt') as f:
            f.write(html)
        if p['info']['id'].replace('-','') == rootid:
            with open(OUTDIR+'index.html','wt') as f:
                f.write(html)

        # summary for emailing
        pageurl = SITE_ROOT + slug
        # TODO - provide downscaled versions
        fullurlmap = {k:SITE_ROOT + v for k,v in urlmap.items()}
        articles = summarizePage(p)
        html = '<div class="connect-mail"><style>%s</style>' % open('resources/connect.css','rt').read()
        for i,ar in enumerate(articles):
            href = ARTICLE_SLUG_PLACEHOLDER if ar.pop(0) else ''
            article = blocksToHtml(ar, fullurlmap)
            if SUMMARY_READMORE_PLACEHOLDER in article:
                more= '&nbsp;<a href="%s">lire la suite...</a>' % href
                article = article.replace(SUMMARY_READMORE_PLACEHOLDER, more)
            elif href:
                more= '<a href="%s">Lire la suite...</a>' % href
                article = article + more
            dest = textToSlug(formatBlockText(ar[0]))
            article = article.replace(ARTICLE_SLUG_PLACEHOLDER, pageurl + '#' + dest)
            article = re.sub(r'\\.(jpg|jpeg)"', r'-s320x\1"', article)
            article = article.replace('-s320x','-s320.') #avoid multi suffixing
            html += '<div class="connect-%s">%s</div>' % ('lead' if i==0 else 'article', article)
        html += '</div>'
        mailablemsg = inline_css(html)
        mailablemsg = mailablemsg.replace('<html>','<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>')

        with open(OUTDIR+slug+'.summary.html','wt') as f:
            f.write(mailablemsg)
    
