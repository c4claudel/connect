from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
#from googleapiclient.errors import HttpError

from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from argparse import ArgumentParser
import bs4
import os.path
import base64
import hashlib

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
TOKEN_FILE = 'gmail-token.json'

def Soup(html):
    return bs4.BeautifulSoup(html, 'lxml')

def djb2(text):
    h = 5381
    for c in text: h = ord(c) + ((h << 5) + h)
    return h

class Mailer():
    def __init__(self, fromaddr, commit=False, reauth=False):
        creds = None
        if not reauth and os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('gmail-credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

        self._service = build('gmail', 'v1', credentials=creds)
        self._from = fromaddr
        self._commit = commit

    def send(self, subject, soup, to=None, cc=None, bcc=None):
        message = MIMEMultipart('alternative')
        message['From'] = self._from
        message['Subject'] = subject
        if to: message['To'] = ', '.join(to) if isinstance(to,list) else to
        else: message['To'] = self._from
        if cc: message['Cc'] = ', '.join(cc) if isinstance(cc,list) else cc
        if bcc: message['Bcc'] = ', '.join(bcc) if isinstance(bcc,list) else bcc

        message.attach( MIMEText(soup.text, 'plain') )
        message.attach( MIMEText(str(soup), 'html') )

        raw_message = base64.urlsafe_b64encode(message.as_string().encode("utf-8"))
        gmail_message = { 'message': { 'raw': raw_message.decode('utf-8') } }

        #print(message)
        draft = self._service.users().drafts().create(userId="me", body=gmail_message).execute()
        print(f"created draft {draft}")
        
        if self._commit:
            result = self._service.users().drafts().send(userId="me", body=draft).execute()
            print(f"sent message result={result}")

            ##ERROR occasionally
            #raise HttpError(resp, content, uri=self.uri)
            #googleapiclient.errors.HttpError: <HttpError 400 when requesting https://gmail.googleapis.com/gmail/v1/users/me/drafts/send?alt=json returned "Precondition check failed.".
            #Details: "[{'message': 'Precondition check failed.', 'domain': 'global', 'reason': 'failedPrecondition'}]">
        else:
            print("not sending without --commit")

    def batchSend(self, batchSize, subject, soup, **kwargs):
        recp = kwargs
        if recp.get('to'): raise Exception("can't batch with TO")
        if recp.get('cc'): raise Exception("can't batch with CC")
        if not recp.get('bcc'): raise Exception("can only batch with BCC")

        bcc = list(recp.get('bcc'))
        while len(bcc):
            count = min(batchSize, len(bcc))
            recp['bcc'] = bcc[:count]
            bcc = bcc[count:]
            print('sending to', len(recp['bcc']))
            self.send(subject, soup, **recp)
            
class Tracker():
    def __init__(self, mailer, shotid):
        self._mailer = mailer
        self._shotid = shotid
        self._uids = {}
    def encode(self, uid):
        if not uid in self._uids:
            #self._uids[uid] = hashlib.md5(uid.encode('utf-8')).hexdigest()[:8]
            self._uids[uid] = djb2(uid)
            print(self._uids)
        return self._uids[uid]
    def link(self, url, uid=None):
        return 'https://shot.c4claudel.com/'+shotid+'/'+uid
    def send(self, subject, html, text=None, **kwargs):
        for node in html.findAll('a'):
            if node.has_attr('href'):
                print('LINK:',node['href'])
        
        for addrmode in ['to', 'cc', 'bcc']:
            if addrmode in kwargs:
                for addr in kwargs[addrmode]:
                    headers = { addrmode: addr }
                    mailer.send(subject, html, text, **headers)
    
            
if __name__ == '__main__':
    Options = ArgumentParser(description='Scraper cms prober')
    Options.add_argument('--html', type=str, required=True)
    Options.add_argument('--subject', type=str, required=True)
    Options.add_argument('--footer', type=str)
    Options.add_argument('--fr', type=str, default='c4claudel@gmail.com')
    Options.add_argument('--to', type=str)
    Options.add_argument('--cc', type=str)
    Options.add_argument('--bcc', type=str)
    Options.add_argument('--batch', type=int, default=0)
    Options.add_argument('--commit', action='store_true', default=False)
    Options.add_argument('--reauth', action='store_true', default=False)
    opts = Options.parse_args()


    mailer = Mailer(opts.fr, commit=opts.commit, reauth=opts.reauth)

    html = open(opts.html,'rt').read()
    soup = Soup(html)

    if '[email&#160;protected]' in html:
        raise 'message contains redacted email address!!'    
    
    if opts.footer:
        footer = open(opts.footer,'rt',encoding="ISO-8859-1").read()
        for foot in Soup(footer).body.children:
            soup.html.body.append(foot)

    headers = {}
    for addrmode in ['to', 'cc', 'bcc']:
        src = opts.__dict__.get(addrmode)
        if src and os.path.exists(src):
            addrs = open(src,'rt',encoding='ISO-8859-1').read().split('\n')
            headers[addrmode] = [a for a in addrs if '@' in a and not a.startswith('REJECT-')]
            print(repr(headers[addrmode]))
            print('sending', addrmode, 'to', len(headers[addrmode]), 'recipients')
        elif src:
            headers[addrmode] = src.split(',')
            
    if not headers:
        print('ERROR: no recipients specified!')
        exit(1)

    if opts.batch:
        mailer.batchSend(opts.batch, opts.subject, soup, **headers)
    else:
        mailer.send(opts.subject, soup, **headers)

