from argparse import ArgumentParser
from bs4 import BeautifulSoup, Tag, NavigableString
from inlinestyler.utils import inline_css
import re

IMAGES_PER_ARTICLE = 1
WORDS_PER_ARTICLE = 40
SITE_ROOT = 'https://connect.c4claudel.com/'

FORBIDDEN_CSS = ['display', 'flex', 'fill', 'word-break', 'white-space', 'word-wrap', 'caret-color', 'align-items', 'font-size']

def notionToSoup(html):
    for styl in FORBIDDEN_CSS:
        html = re.sub(styl+': [^;]*;', '', html)
    soup = BeautifulSoup(html, features="html5lib")
    emojis = soup.findAll('img',{'class':'notion-emoji'})
    for em in emojis:
        print(em['alt'])
        em.replace_with(NavigableString(em['alt']))
    pseuds = soup.findAll('div',{'class':'pseudoSelection'})
    for em in pseuds:
        print('REMOVE', em['class'])
        em.extract()
    return soup

def summarizeSoup(soup):
    content = soup.findAll('div',{'class':'notion-page-content'})[0]
    summaryItems = []
    anchors = {}
    currentArticle = None
    currentWords = 0
    currentImages = 0
    currentTruncation = 0
    currentAnchor = None
    blocks = list(content.children)            
    while blocks:
        block = blocks.pop(0)
        bclass = [c.split('-')[-2] for c in block['class'] if '-block' in c][0]
        if bclass == 'column_list':
            columns = block.findAll('div',{'class':'notion-column-block'})
            print('COLUMNS: ', len(columns))
            colels = [b for c in columns for b in c]
            blocks = colels + blocks
        elif bclass == 'header':
            print('HEAD',block.text)
            currentArticle = Tag(name='article', attrs={'class':'connect-article'})
            aref = 'a-%d'%len(summaryItems)
            currentAnchor = SITE_ROOT + f.split('/')[-1] + '#'+ aref
            header = Tag(name='h2')
            header.append(block)
            #TODO in full doc: currentArticle.append(Tag(name='a',attrs={'id':currentAnchor}))
            currentArticle.append(header)
            summaryItems.append(currentArticle)
            currentWords = 0
            currentImages = 0
            currentTruncation = 0
            if block['data-block-id']:
                anchors[block['data-block-id']] = aref
        elif bclass == 'callout':
            if 'cette edition' in str(block):
                print('DROPTOC',block.text[:40])
            else:
                print('BOXX',block.text[:40])
                currentArticle = Tag(name='div', attrs={'class':'connect-box'})
                currentArticle.append(block)
                summaryItems.append(currentArticle)
        elif bclass == 'image' and currentArticle:
            if currentImages < IMAGES_PER_ARTICLE:
                print('ARTIMG', block.find('img')['src'])
                im = Tag(name='img', attrs={'class': 'connect-thumb',
                                            'src': SITE_ROOT + block.find('img')['src']})
                if currentAnchor:
                    an = Tag(name='a', attrs={'href': currentAnchor})
                    an.append(im)
                    im = an
                currentArticle.insert(1,im) #after header
            else:
                print('DROPIMG', block.find('img')['src'])
                currentTruncation += 1
            currentImages += 1
        elif bclass == 'text' and currentArticle:
            if currentWords < WORDS_PER_ARTICLE:
                print('ARTTXT', block.text[:40], currentWords)
                p = Tag(name='div', attrs={'class': 'connect-summary'})
                p.append(NavigableString(block.text))
                currentArticle.append(p)
            else:
                print('DROPTXT', block.text[:40], currentWords)
                currentTruncation += 1
            currentWords += len(block.text.split())
        elif bclass != 'image' and not currentArticle:
            print('LEAD', bclass, block.text[:40])
            b = Tag(name='div', attrs={'class':'connect-lead'})
            b.append(block)
            summaryItems.append(b)
        else:
            print('????', bclass, block.text[:40])

        if currentTruncation == 1:
            more = Tag(name='a', attrs={'class':'connect-read-more', 'href': currentAnchor})
            more.append(NavigableString("Continue..."))
            last = list(currentArticle.children)[-1]
            print('TRUNC:',last)
            if last.name == 'div':
                last.append(NavigableString(' '))
                last.append(more)
            else:
                currentArticle.append(more)                    
    return summaryItems, anchors
    
def makeMailableSummary(summaryItems):
    temp = open('resources/summary_template.html','rt').read()
    summ = BeautifulSoup(temp, features="html5lib")
    summ.body.div.extend(summaryItems)
    mailablemsg = inline_css(str(summ))
    soup = BeautifulSoup(mailablemsg, features="html5lib")
    return soup.body.div

def makeAnchoredHtml(html, anchors):
    soup = BeautifulSoup(html, features="html5lib")
    for did,anchor in anchors.items():
        ax = Tag(name='a', attrs={'id': anchor})
        el = soup.find('div',{'data-block-id': did})
        el.insert_before(ax)
    
    
if __name__ == '__main__':
    Options = ArgumentParser(description='Newsletter Summarizer')
    Options.add_argument('--create-index', type=str, nargs='?')
    Options.add_argument('--anchor-original', action='store_true')
    Options.add_argument('files', type=str, nargs='+')
    opts = Options.parse_args()

    for f in opts.files:        
        with open(f,'rt') as fin:
            orig = fin.read()
            soup = notionToSoup(orig)
            summaryItems,anchors = summarizeSoup(soup)

            mail = makeMailableSummary(summaryItems)
            with open(f+'.summary.html','wt') as fout:
                fout.write(str(mail))

            news = makeAnchoredHtml(orig, anchors)
            newsfile = f+'.anchored.html' if not opts.anchor_original else f
            with open(newsfile,'wt') as fout:
                fout.write(str(news))
