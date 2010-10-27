#Copyright (c) 2010 John McLaughlin -- Mass Animation
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE. 

from google.appengine.ext.webapp import util
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from django.utils import simplejson as json
from google.appengine.api import urlfetch
from google.appengine.api import memcache

from  google.appengine.runtime import DeadlineExceededError

import sys
import os
import re
import cgi,urllib,mimetypes
import hashlib,base64,hmac
import time
import unittest


def compute_signature(msg):
    """This computes the signature for a cURL Server request."""
    hashkey = memcache.Client().get('CURL_TEST_SERVER_HASHKEY')
    h = hmac.new(hashkey, msg, hashlib.sha1)
    signature = urllib.quote(base64.b64encode(h.digest()))
    return signature

class DownloadTryAgainError (urlfetch.DownloadError):
    """This is raised when a test somewhat expectedly times out."""
    pass

class CurlTestBase(unittest.TestCase):
    """Base class for all the cURL Server tests.  It's function is
    to send the requests, and to collect verbosity output."""
    _test_count = 0
    _verbosity = 0
    _verbose_output = ''
    _teardown = 1
    
    def __init__(self, methodName):
        super(CurlTestBase,self).__init__(methodName)
        CurlTestBase._test_count += 1
    
    @classmethod
    def send_request(cls,options,request):
#        request['jsonrpc'] = '2.0'
#        request['id'] = CurlTestBase._test_count
        request_str = json.dumps(request)
        server = memcache.Client().get('CURL_TEST_SERVER_DNS')
        signature = compute_signature(request_str)
        url = 'http://' + server + '/cgi-bin/jsonrpc.py?signature='+signature + options ## options async, log, env, tmpdir
        try:
            result = urlfetch.fetch(url=url,
                                payload = request_str,
                                method = 'POST',
                                allow_truncated=True,
                                headers={
                                             'Content-Type': 'application/json',
                                             'Accept' : 'application/json'
                                             },
                                deadline=10  ## google web apps max seconds)
                                )
        except urlfetch.DownloadError:
            raise DownloadTryAgainError("Most likely a timeout. It may take a couple tries for GAE to cache the necessary files for the test.")
            
        ### Verbose output.
        if CurlTestBase._verbosity:
            CurlTestBase._verbose_output += 'Request:' + json.dumps(request) + '\n'
            result_str = result.content
            try:
                result_parsed = json.loads(result.content)
                if 'error' in result_parsed:
                    if 'data' in result_parsed['error']:
                        result_str += 'SERVER ERROR: ' + result_parsed['error']['data'] + '\n'
                if 'result' in result_parsed:
                    result_str += 'SERVER RESULT: ' + result_parsed['result'] + '\n'
            except:
                pass
            CurlTestBase._verbose_output += 'Response:' + result_str + '\n'
        return result

######################################
#####  BASIC TESTS ###################
######################################
# This one can be run from the development server.
class CurlTestAwake(CurlTestBase):
    
    def setUp(self):
        pass

    def test_rpc_sync_ping(self):
        ## Test that curl service is awake.
        request = {
            'jsonrpc': '2.0',
            'id': 0,
            'method': 'ping'
        }
        response = self.send_request('&log=1',request)
        result = json.loads(response.content)
        self.assertEqual(result['result'],True)
            
        
    def test_rpc_sync_help(self):
        ## Test that "curl" works.
        request = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'curl',
            'params': ['--version']
        }
        response = self.send_request('&log=1',request)
        result = json.loads(response.content)
        self.assertEqual(result['result'][:11],'curl 7.15.5')
    
    def test_curl_aws_metadata(self):
        ## Test that AWS meta-data works.
        request = {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'curl',
            'params': ['http://169.254.169.254/latest/meta-data/public-hostname']
        }
        response = self.send_request('&log=1',request)
        result = json.loads(response.content)
        self.assertEqual(result['result'], memcache.Client().get('CURL_TEST_SERVER_DNS'))
        
        
    def test_sequence(self):
        """Test that a simple "sequence" method works."""
        request = {
            'jsonrpc': '2.0',
            'id': 7,
            'method': 'sequence',
            'params': [
                {
                    'jsonrpc': '2.0',
                    'id': 8,
                    'method': 'curl',
                    'params': ['http://169.254.169.254/latest/meta-data/public-hostname']
                },
                {
                    'jsonrpc': '2.0',
                    'id': 9,
                    'method': 'ping'
                }
            ]
        }
        response = self.send_request('&log=1',request)
        result = json.loads(response.content)
        self.assertEqual(result['result'][0]['result'],memcache.Client().get('CURL_TEST_SERVER_DNS'))
        self.assertEqual(result['result'][1]['result'],True)
        



###########################################################
########  Blob Tests
###########################################################
# These can't be run from a development server, since the 
# cURL Server must be able to download from GAE for these tests..
class CurlTestBlobEntry(db.Model):
    """Class for holding test data."""
    mytext = db.TextProperty()
    mytext2 = db.TextProperty()
    myblob = blobstore.BlobReferenceProperty()
    
    
class CurlTestBlob(CurlTestBase):
    def setUp(self):
        """ Set up the tests."""
        
        ### Secret messages:
        text1 = r"""
665555432 64 o42o4 o__ __o/4__o__32 __o__564<|\4/|>32 /v3 |4/>2\32 />2\5 64/ \`o3o'/ \32/>3 / \32 \o42\o5364\o/ v\2/v \o/32\32\o/4v\42v\52 64 |2 <\/>2 |4o32|42<\42<\5264/ \4/ \32 <\__2/ \3_\o__</3 _\o__</5264\o/4\o/5554 64 |42|32o54 o54 64/ \4/ \3<|>532_<|>_532 6542/ \42\o__ __o55654o/2 \o4 |3 |>3 o54 6532 <|__ __|>32 / \2 / \3<|>546532 /32 \32 \o/2 \o/3/ \54653 o/4 \o32|3 |3 \o/54653/v42 v\3/ \2 / \3 |54 652 />43 <\5/ \5465555432 65555432 6553o4 o5562\o__ __o__ __o52 <|>32_<|>_52\o__ __o362 |3 |3 |>32o__ __o/3< >5 o__ __o32|3 |>2 62/ \2 / \2 / \3 /v3 |32|4 o32 /v3 v\3/ \2 / \2 62\o/2 \o/2 \o/3/>3 / \3 o__/_3<|>3 />32 <\2 \o/2 \o/2 62 |3 |3 |3 \32\o/3 |4/ \3 \4 /3|3 |362/ \2 / \2 / \3 o32|32|4\o/32o32 o3/ \2 / \2 6532<\__2/ \3 o4 |32 <\__ __/>56553<\__3 / \5432 65555432 6655Acrobatic font by Randy Ransom via Figlet6552 '
"""
        text2 = r"""
62@@@@@@@3@@@@@@3@@@@@@@2@@@2@@@2 @@@@@@2 62@@@@@@@@2@@@@@@@@2@@@@@@@@2@@@2@@@2@@@@@@@2 62@@!2@@@2@@!2@@@2!@@32 @@!2!@@2!@@32 62!@!2@!@2!@!2@!@2!@!32 !@!2@!!2!@!32 62@!@!!@!2 @!@2!@!2!@!32 @!@@!@!2 !!@@!!362!!@!@!3!@!2!!!2!!!32 !!@!!!3 !!@!!!2 62!!: :!!2 !!:2!!!2:!!32 !!: :!!4!:!262:!:2!:!2:!:2!:!2:!:32 :!:2!:!32!:!2 62::2 :::2::::: ::2 ::: :::2 ::2:::2:::: ::2 62 :2 : :2 : :2:3:: :: :2 :2 :::2:: : :26 655 Poison font by Vinney Thai via Figlet6        
        """

        def decode(str):
            """This just decodes the above strings into something 
            meaningful."""
            s6 = re.sub('6','\n',str)
            s5 = re.sub('5','44',s6)
            s4 = re.sub('4','33',s5)
            s3 = re.sub('3','22',s4)
            return re.sub('2','  ',s3)
                                                              
        self.item = CurlTestBlobEntry(mytext=decode(text1), mytext2=decode(text2))
        self.item.put();
    
    def tearDown(self):
        """This tears down up to 10 tests at a time.  Typically it will
        only clean up the last test.  But if someone looked at their results
        by using the "teardown=0" option.  This would clean up those as well."""
        if CurlTestBase._teardown:
            memcache.Client().set('curl_test_upload','')
            q = CurlTestBlobEntry.all()
            item_list = q.fetch(10)  ## normally there's just one of these
            for item in item_list:
                try:
                    item.myblob.delete()
                except Exception:
                    pass
                item.delete()
                
   
class CurlTestBlobSync(CurlTestBlob):     
    
    def test_get_text(self):
        """Test that curl can get a small blob from our datastore."""
        request = {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'curl',
            'params': ['http://' + os.environ['SERVER_NAME'] + '/curl_test/data?serve=mytext&key='+ str(self.item.key())]
        }
        response = self.send_request('&log=1',request)
        result = json.loads(response.content)
        self.assertEqual(result['result'], self.item.mytext)
    
    
    def test_blobstore_upload(self):
        """Test that the cURL Server can get a blob from the GAE datastore and 
        upload it to the blobstore."""
        upload_as = 'my_blobstore_file.txt'
        item_key = str(self.item.key())
        request = { 
            'jsonrpc': '2.0',
            'id': 6,
            'method': 'sequence',
            'params' : [
                {
                'jsonrpc': '2.0',
                'id': 4,
                'method': 'curl',
                'params': [
                           '-o',
                           'my_silly_blob',
                           'http://' + os.environ['SERVER_NAME'] + '/curl_test/data?serve=mytext&key=' + item_key
                           ]
                }, 
                {
                'jsonrpc': '2.0',
                'id': 5,
                'method': 'curl',
                'params': ['-F',
                           ('file=@my_silly_blob;type=text/plain;filename='+upload_as),
                           blobstore.create_upload_url('/curl_test/finish_upload?key=' + item_key)
                          ]
                }
            ]
        }
        response = self.send_request('&log=1',request)
        self_item_refreshed = db.get(item_key) # Apparently self.item caches myblob as None.
        ## The response and result aren't really needed in this but they may be
        ## useful for debugging.
        result = json.loads(response.content)
        
        blob_reader = blobstore.BlobReader(self_item_refreshed.myblob.key())
        blob_text = blob_reader.read()
        self.assertEqual(self.item.mytext,blob_text)
    
    
class AsyncTestWaitError(DeadlineExceededError):
    pass


class CurlTestBlobASync(CurlTestBlob): 
        
    def test_blobstore_concat(self):
        """Test that the cURL Server can get two datastore items, concatenate them,
        and upload them to the Blobstore."""
        memcache.Client().set('curl_test_upload','')
        upload_as = 'my_blobstore_async.txt'
        item_key = str(self.item.key())
        request = { 
            'jsonrpc': '2.0',
            'id': 10,
            'method': 'sequence',
            'params' : [
                {
                'jsonrpc': '2.0',
                'id': 11,
                'method': 'curl',
                'params': [
                           '-o',
                           'my_silly_blob',
                           'http://' + os.environ['SERVER_NAME'] + '/curl_test/data?serve=mytext&key=' + item_key,
                           '-o',
                           'my_other_blob',
                           'http://' + os.environ['SERVER_NAME'] + '/curl_test/data?serve=mytext2&key=' + item_key,
                           ]
                },
                {
                'jsonrpc': '2.0',
                'id': 13,
                'method': 'cat',
                'params': ['my_silly_blob', 'my_other_blob', '>', 'to_upload']
                },
                {
                'jsonrpc': '2.0',
                'id': 12,
                'method': 'curl',
                'params': ['-F',
                           ('file=@to_upload;type=text/plain;filename='+upload_as),
                           blobstore.create_upload_url('/curl_test/finish_upload?key=' + item_key)
                          ]
                }
            ]
        }
        response = self.send_request('&log=1&async=1',request)
        ## The response and result aren't really needed in this but they may be
        ## useful for debugging.
        result = json.loads(response.content)
        
        try:
            ## So this is the really stupid part where we wait for a response
            ## from an asynchronous request. 
            mckey = memcache.Client().get('curl_test_upload')
            i = 0
            while i < 30:
                i += 1
                mckey = memcache.Client().get('curl_test_upload')
                if mckey:
                    break
                time.sleep(1)
                
            self_item_refreshed = db.get(item_key) # Apparently self.item caches myblob as None.
            
            blob_reader = blobstore.BlobReader(self_item_refreshed.myblob.key())
            blob_text = blob_reader.read()
            self.assertEqual(self.item.mytext+self.item.mytext2, blob_text)
            
        except DeadlineExceededError:
            raise AsyncTestWaitError("Timed out while waiting for asynchronous request to respond.  You would never do this.  Try the test again.")
            

try:
    from site_settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
except Exception:
    AWS_ACCESS_KEY_ID = 'Put your access key id here.'
    AWS_SECRET_ACCESS_KEY = 'Put your secret access key here.'


def aws_signature(bucket,keypath,expires,secret_access_key=''):
    """
    The magic incantation for creating a canonical aws signature.
    """
    sign_msg = ('GET\n\n\n'+expires+'\n' +'/'+bucket+'/'+keypath)
    h = hmac.new(secret_access_key, sign_msg, hashlib.sha1)
    signature = urllib.quote(base64.b64encode(h.digest()))
    return (signature,sign_msg)


class CurlTestBlobS3(CurlTestBlob):
    
    def test_upload_from_s3(self):
        
        s3path = 's3://massanimation-testdata/curl_test/mass_animation_label.png'
        upload_as = 'shameless_massanimation_plug.png'
        
        s3parse = re.search(
            r's3://(?P<bkt>[^/]*)/(?P<key>(?P<dir>(?:[^/]*/)*)(?P<fn>[^/]*$))',
            s3path).groupdict()
            
            
        ### curl parameters for download from S3 to EC2
        expires = str(int(time.time() + 3600))
        signature = aws_signature(s3parse['bkt'],s3parse['key'],
                        expires,secret_access_key=AWS_SECRET_ACCESS_KEY)[0]
        http_path = ('http://'+s3parse['bkt']+'.s3.amazonaws.com/'+s3parse['key']
            + '?AWSAccessKeyId='+AWS_ACCESS_KEY_ID+'&Expires='+expires
            + '&Signature='+signature )
        
        ### curl parameters for upload from EC2 to GAE
        mime_type = mimetypes.guess_type(upload_as)[0]
        if not mime_type:
            mime_type = 'application/octet-stream'

        memcache.Client().set('curl_test_upload','')
        item_key = str(self.item.key())
        request = { 
            'jsonrpc': '2.0',
            'id': 14,
            'method': 'sequence',
            'params' : [
                {
                'jsonrpc': '2.0',
                'id': 15,
                'method': 'curl',
                'params': ['-o', s3parse['key'], '--create-dirs', http_path]
                },
                {
                'jsonrpc': '2.0',
                'id': 16,
                'method': 'curl',
                'params': ['-F',              
                           ('file=@'+s3parse['key']+';type='+mime_type+';filename='+upload_as),
                           blobstore.create_upload_url('/curl_test/finish_upload?key=' + item_key)
                          ]
                }
            ]
        }
        response = self.send_request('&log=1&async=1',request)
        ## The response and result aren't really needed in this but they may be
        ## useful for debugging.
        result = json.loads(response.content)
        
        try:
            ## So this is the really stupid part where we wait for a response
            ## from an asynchronous request. 
            mckey = memcache.Client().get('curl_test_upload')
            i = 0
            while i < 30:
                i += 1
                mckey = memcache.Client().get('curl_test_upload')
                if mckey:
                    break
                time.sleep(1)
                
            self_item_refreshed = db.get(item_key) # Apparently self.item caches myblob as None.
            self.assertEqual(upload_as,self_item_refreshed.myblob.filename)
        except DeadlineExceededError:
            raise AsyncTestWaitError("Timed out while waiting for asynchronous request to respond.  You would never do this.  Try the test again.")    


class CurlTestBlobUploadHandler (blobstore_handlers.BlobstoreUploadHandler):
    """ Handler for finishing the uploads to the Blobstore."""
    def post(self):
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        item_key = self.request.get('key')
        item = db.get(item_key)
        item.myblob = blob_info
        item.put()
        memcache.Client().set(key='curl_test_upload', 
                              value=blob_info.key(), time=3600)
        ## This redirection isn't really important, since cURL Server isn't
        ## really listening for it.
        self.redirect('/curl_test/data?serve=blob&key=' + str(item_key) )
        
        
class CurlTestDataServeHandler (blobstore_handlers.BlobstoreDownloadHandler):
    """ Handler for downloading data to the cURL Server."""
    def get(self):
        serve_type = self.request.get('serve', default_value='mytext')
        item_key = self.request.get('key')
        item = db.get(item_key)
        if serve_type == 'mytext':
            self.response.out.write(item.mytext)
        elif serve_type == 'mytext2':
            self.response.out.write(item.mytext2)
        else:
            self.send_blob(item.myblob)
        
        
class CurlTestHandler(webapp.RequestHandler):
    """Main application handler."""
    
    def run_diagnostics(self):
        """Runs the cURL Server diagnositics."""
        request = {
            'jsonrpc': '2.0',
            'id': 0,
            'method': 'ping'
        }
        result = CurlTestBase.send_request('&diag=1', request)
        response = '<html><body><pre>'
        response += cgi.escape(result.content)
        response += '</pre></body></html>'
        self.response.out.write(response)
        
        
    def welcome(self):
        """ Front page. """
        mc = memcache.Client()
        server = mc.get('CURL_TEST_SERVER_DNS')
        if not server:
            server = '';
        hashkey = mc.get('CURL_TEST_SERVER_HASHKEY')
        if not hashkey:
            hashkey = '';
        response = """
        <html><head><title>cURL Server Test Suite
            </head><body><div style="margin:15px">
        <h1>cURL Server Test Suite</h1>
        <p>This is an interface to the cURL Server Test Suite on Google App
        Engine.  In addition to testing the server it also demonstrates a
        few possible use cases in conjunction with GAE.  Please see the home
        page of the server for details about the server itself.
        </p>
        <form method="POST" action="/curl_test">
        If the info below is not correct please upload new server info to the 
        GAE memcache.</br></br>
        <input type="text" size="60" name="server" value="%s"/>&nbsp;&nbsp;
            <b>cURL Server DNS</b> (e.g. 
            <code>ec2-204-236-157-181.us-west-1.compute.amazonaws.com</code> 
            )<br/>
        <input type="text" size="60" name="hashkey" value="%s"/>&nbsp;&nbsp;
            <b>cURL Server hashkey</b> Usually the Private DNS. (e.g.  
            <code>ip-10-163-150-100.us-west-1.compute.internal</code> 
            )<br/>
        <input type="submit" value="Submit Server Info"><br/>
        </form>
        <h3>The Tests</h3>
        (Submit the server info above, before running these tests.)
        <ol>
            <li><a href="/curl_test?verbosity=1&suite=awake">
                /curl_test?verbosity=1&suite=awake</a>&nbsp;
                Test that server is alive and collect some basic info.  
                This can be run from the development server.</li>
            <li><a href="/curl_test?verbosity=1&teardown=1&suite=sync">
                /curl_test?verbosity=1&teardown=1&suite=sync</a> &nbsp;This runs 
                two tests. The first is a simple download from the datastore
                to the cURL Server.  The second is a round trip from
                the datastore to the cURL Server and back to the Blobstore.
                <b>This test may time out</b> one or two times before
                succeeding.  This is expected behavior for synchronous mode.
                Set "teardown=0" in the URL to prevent the resulting
                datastore/blobstore items from being deleted. </li>
            <li><a href="/curl_test?verbosity=1&teardown=1&suite=async">
                /curl_test?verbosity=1&teardown=1&suite=async</a> &nbsp;This
                test creates a compound "sequence" request which concatenates 
                two datastore items and uploads them to the blobstore.  The
                request is asynchronous, so it will return right away.  However
                after the request returns, this test stupidly waits for the 
                cURL Server upload to finish, so it may time out as well.
                In production you'd probably do your polling from the browser 
                with AJAX style communication.</li>
            <li><a href="/curl_test?verbosity=1&teardown=1&suite=s3">
                /curl_test?verbosity=1&teardown=1&suite=s3</a> &nbsp; Testing
                transfer from S3 to GAE Blobstore.  To run this test replace 
                the value of "s3path" in
                <code>curl_test.py</code> with your test S3 file path.  You
                will also need your AWS_ACCESS_KEY_ID, and 
                AWS_SECRET_ACCESS_KEY.  You can hard code them or put them
                into a "site_settings" module.  See the code for details.  As
                with the previous tests, to keep the test result around set
                "teardown=0".</li>
        </ol>
        <h3>Other Links</h3>
        <ul>
            <li><a href="/curl_test?diag=1">
                /curl_test?diag=1</a> &nbsp; Run the cURL Server diagnostics.
                This can also be run from the development server.</li>
            <li><a href="http://%s">Your Server Home Page.</a></li>
            <li><a href="http://%s/curl_web_client.html">Your cURL Web Client</a></li>
        </ul>
        <br/>
        </div></body></html>
        """ % (server, hashkey, server, server)
        self.response.out.write(response)
        
        
    def post(self):
        """Submission of CURL_TEST_SERVER_DNS, CURL_TEST_SERVER_HASHKEY"""
        mc = memcache.Client()
        mc.set('CURL_TEST_SERVER_DNS', self.request.get('server'))
        mc.set('CURL_TEST_SERVER_HASHKEY', self.request.get('hashkey'))
        self.redirect('/curl_test')
        
        
    def get(self):
        """Main request and test dispatcher."""
        diag = int(self.request.get('diag', default_value=False))
        if diag:
            self.run_diagnostics()
            return
        
        run_suite = self.request.get('suite', default_value=None)
        if not run_suite:
            self.welcome()
            return
        
        ## verbosity should probably be on always.
        verbosity = self.request.get('verbosity', default_value='0')
        ## teardown controls whether or not the tests clean up after themselves.
        teardown = int(self.request.get('teardown', default_value='1'))
        
        ## These are sort of like global variables.  Sloppy programming I know.
        CurlTestBase._verbosity = int(verbosity)
        CurlTestBase._verbose_output = ''
        CurlTestBase._teardown = teardown
        
        ## The test suites to select from.
        suite_dict = {}
        suite_dict['awake'] = unittest.TestLoader().loadTestsFromTestCase(CurlTestAwake);
        suite_dict['sync'] = unittest.TestLoader().loadTestsFromTestCase(CurlTestBlobSync);
        suite_dict['async'] = unittest.TestLoader().loadTestsFromTestCase(CurlTestBlobASync);
        suite_dict['s3'] = unittest.TestLoader().loadTestsFromTestCase(CurlTestBlobS3);
        result = unittest.TestResult()
        
        ## Run the selected suite
        suite_dict[run_suite].run(result)
#        suite.debug()

        ## Bare bones result output.
        response = '<html><body>'
        response += '<h3>Summary:</h3><pre>' + cgi.escape(repr(result)) + '</pre>'
        if len(result.errors):
            for e in result.errors:
                response += '<h4>' + str(e[0]) + '</h4>'
                response += '<pre>' + e[1] + '</pre>'
        if CurlTestBase._verbosity:
            response += '<pre>' + cgi.escape(CurlTestBase._verbose_output) + '</pre>'
        response += '</body></html>'
        self.response.out.write(response)
        

def main():
    application = webapp.WSGIApplication([
                                        ('/curl_test/finish_upload.*', CurlTestBlobUploadHandler),
                                        ('/curl_test/data.*', CurlTestDataServeHandler),
                                        ('/curl_test.*', CurlTestHandler),
                                        ],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()


                                                                      
    