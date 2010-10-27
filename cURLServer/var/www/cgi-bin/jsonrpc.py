#! /usr/bin/python

# Copyright (c) 2010 John McLaughlin -- Mass Animation

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


## make sure the header gets printed before any other chance of error.
#
# Sending back text/plain because it seems to be slightly more convenient
# especially where non JSON debugging text gets printed. Also it doesn't
# default to download in browers, which messes up the YUI3 iframe IO transport.
# 
# print('Content-type: application/json')
print('Content-type: text/plain')
# print('Connection: close')        ## Mostly for debugging. 
print

import sys
import simplejson as json
import jsonrpcbase
from jsonrpc_procs import rpc_service_setup 
import cgi
import os
import urllib2

import sha, urllib, base64, hmac
import re

# No big deal leaving this turned on.
import cgitb
cgitb.enable()


tmpdir_root = '/tmp/jsonrpc'

def main():

    # This sets up all the json_procs to accessuble for the rpc_service.
    rpc_service = rpc_service_setup()

    # QUERY_STRING could have these options
    #    signature  Required for any service access.  This is an hmak/sha1
    #               hash againt the request string.
    #    diag ..... Run "run_diagnostics"  This allows the user to get a lot
    #               of info on what might be happening on the server.
    #    async .... Send the request to the asynchronous queue.
    #    tmpdir ... User explicitly sets the tmpdir for the task execution.
    #    log ...... Logs the request, response, and environment in
    #               tmpdir/jsonrpc.log
    option_dict = cgi.parse_qs(os.environ['QUERY_STRING'])


    # Check that there is a signature.
    if not 'signature' in option_dict:
        print json.dumps({
            "jsonrpc": "2.0", 
            "error": {"code": -32098, "message": "No signature."}, 
            "id": None});
        return
        pass
  
    # Read the request data.
    form = cgi.FieldStorage()
  
    request_str = ''
    multipart_keys = []
    if form.type == 'multipart/form-data':
        ## Read the "jsonrpc" part, and collect all the names of the file parts.
        for part_key in form.keys():
            if part_key == 'jsonrpc':
                request_str = form['jsonrpc'].value
            else:
                multipart_keys.append(part_key);
    else:
        if not form.file:
            print json.dumps({
                "jsonrpc": "2.0", 
                "error": {"code": -32099, "message": "No post data."}, 
                "id": None});
            return
        request_str = form.file.read()

    # The default hashkey is the local DNS name.  This can be changed to grab
    # the user-data string by uncommenting the code below.
    #
    # The main idea is that we want a hashkey that is easily accessible, but
    # hard to guess. The local DNS fits the bill because an intruder needs to
    # know both the the public and private DNS names to get access to the
    # JSONRPC service.  Instance tags were considered but they require 
    # the AWS_SECRET_ACCESS_KEY to get.  My feeling is that the extra
    # security provided to this instance by using the AWS secret key, isn't 
    # worth the risk of exposing the key.
    #
    ud = None
    ud = urllib2.urlopen('http://169.254.169.254/latest/meta-data/local-hostname')
    #try:
    #    ud = urllib2.urlopen('http://169.254.169.254/latest/user-data')
    #except Exception:
    #    ud = urllib2.urlopen('http://169.254.169.254/latest/meta-data/local-hostname')
    hashkey = ud.read()
    h = hmac.new(hashkey,request_str,sha)
    target_sig = base64.b64encode(h.digest())
    
    if target_sig != option_dict['signature'][0]:
        data = ''
        # data += '~'+hashkey+'~'+request_str+'~'+target_sig+'~'+str(option_dict['signature'][0])+'~'
        print json.dumps({
            "jsonrpc": "2.0", 
            "error": {
                "code": -32097, 
                "message": "Invalid Signature.",
                "data": data
                }, 
            "id": None});
        return

    # output all diagnostic data
    if 'diag' in option_dict and option_dict['diag'][0]:
        diag_info = diagnostic_data(option_dict)
        print json.dumps(diag_info, indent=4)
        return;
   
    # Establish a tmpdir location.
    # A user specified a tmpdir then is relative to tht tmpdir_root.
    # All diretories are created as needed.
    global tmpdir_root
    if 'tmpdir' in option_dict:
        tmpdir = tmpdir_root + '/' + option_dict['tmpdir'][0]
    else:
        tmpdir = tmpdir_root + '/' + str(os.getpid())
    if not os.access(tmpdir,os.F_OK):
        os.makedirs(tmpdir)
    os.chdir(tmpdir)
 
    # Now handle file uploads if necessary
    for part in multipart_keys:
        outfd = open(form[part].filename,'w')

        inbytes = form[part].file.read(1000000)
        while inbytes:
            outfd.write(inbytes)
            inbytes = form[part].file.read(1000000)
        outfd.close()

    result = ''
    if 'async' in option_dict and option_dict['async'][0]:
        ## Item to be put in the async queue.  Currently just need a tmpdir
        ## and the request.
        async_item = {
                'tmpdir': tmpdir, 
                'request': json.loads(request_str)
                }
        rpc_queue_dir = '/tmp/jsonrpc_queue'
        queue_path = rpc_queue_dir + '/' + str(os.getpid())
        f = open(queue_path,'w')
        f.write(json.dumps(async_item))

        result = json.dumps({'queue_path': queue_path })
        print json.dumps({
            "jsonrpc": "2.0", 
            "result": json.loads(result),
            "id": None
            });
    else:
        # synchronous execution.
        result = rpc_service.call(request_str)
        print result
    
    if 'log' in option_dict and option_dict['log'][0]:
        # Logs request, response, and environment to "tmpdir/jsonrpc.log"
        log_fd = open('jsonrpc.log','w')
        log_fd.write('{"Request":' + request_str + ', ')
        log_fd.write('"Result":' + json.dumps(result) + ', ')

        log_fd.write('"Environment": [')
        env_keys = sorted(os.environ.keys())
        env_out = ''
        for k in env_keys:
            env_out += '["'+k+'"' + ', '+ json.dumps(os.environ[k]) + '], '
        
        log_fd.write(env_out[:-2]+']}')
        log_fd.close()


def diagnostic_data(option_dict):
    "Dump of everything relevant to the tasks and queue."
    cgitb.enable()
    diag = {
            'jsonrpc.log': {
                'info': 'This contains the request, result, and linux environment of the request.',
                'data': None 
                },
            'tmpdir_list': {
                'info': 'Directory listing of the tmpdir.',
                'data':[]
                },
            'tmpdir': {
                'info': 'tmpdir path',
                'data': None
                },
            'daemon_running': {
                'info': 'Is the daemon running for the async queue?',
                'data': False
                },
            'queue_list': {
                'info': 'Listing of the queued tasks.  Normally this is empty.',
                'data': None
                },
            'queue_request': { 
                'info': 'Request passed to async jsonrpc daemon.',
                'data': None
                },
            'queue_stderr': { 
                'info': 'Daemon crash data.',
                'data': None
                },
            'queue_stdout': {
                'info': 'This generally only contains data when the daemon crashes.',
                'data': None
                }
            }
    global tmpdir_root
    prev_pid = ''
    if 'tmpdir' in option_dict:
        if option_dict['tmpdir'][0][0] == '/':
            tmpdir = option_dict['tmpdir'][0]
        else:
            prev_pid = option_dict['tmpdir'][0]
            tmpdir = tmpdir_root+ '/' + option_dict['tmpdir'][0]
    else:
        tmpdir_list = os.listdir(tmpdir_root)
        if tmpdir_list:
            newest = tmpdir_list[0]
            newest_time = os.stat(tmpdir_root + '/' + newest).st_mtime
            for d in tmpdir_list[1:]:
                d_time = os.stat(tmpdir_root + '/' + d).st_mtime
                if d_time > newest_time:
                    newest = d
                    newest_time = d_time
            tmpdir = tmpdir_root + '/' + newest
            prev_pid = newest

    os.chdir(tmpdir)

    diag['tmpdir']['data'] = tmpdir
    try:
        log_contents = open('jsonrpc.log').read()
        log_json = ''
        try:
            log_json = json.loads(log_contents)
            diag['jsonrpc.log']['data'] = log_json
        except Exception:
            diag['jsonrpc.log']['data'] = log_contents
            #raise
    except Exception:
        #raise
        pass

    try: 
        diag['tmpdir_list']['data'] = os.listdir(tmpdir)
    except Exception:
        pass
    
    try:
        req_file = tmpdir + '/_request'
        if os.access(req_file,os.F_OK):
            request_str = open(req_file).read()
            try:
                diag['queue_request']['data'] = json.loads(request_str)
            except Exception:
                diag['queue_request']['data'] = request_str
    except Exception:
        pass
   
    try:
        pid_file = '/tmp/jsonrpc_daemon.pid'
        if os.access(pid_file,os.F_OK):
            pid = open(pid_file).read().strip()
            diag['daemon_running']['data'] = os.access('/proc/'+pid,os.F_OK) 
    except Exception:
        pass
    try: 
        queue_file_list = os.listdir('/tmp/jsonrpc_queue')
        queue_list = []
        for file in queue_file_list:
            item = {'task_id': file}
            try: 
                item['task'] = open('/tmp/jsonrpc_queue/'+file).read()
            except Exception:
                psss
            queue_list.append(item)
        diag['queue_list']['data'] = queue_list
    except Exception:
        pass
    try:
        diag['jsonrpc_stderr']['data'] = open('/tmp/jsonrpc_stderr').read()
    except Exception:
        pass
    try:
        diag['jsonrpc_stdout']['data'] = open('/tmp/jsonrpc_stdout').read()
    except Exception:
        pass
    return diag

main()

