#!/usr/bin/env python

# Copyright (c) 2010 John McLaughlin -- Mass Animation

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


import sys, time, os, shutil
from daemon import Daemon
import simplejson as json
import jsonrpcbase
from jsonrpc_procs import rpc_service_setup

# Boto and the AWS access keys would be used if this were extended to
# use SQS.  Currently they aren't necessary.  SQS can take up to a couple
# minutes to queue and allocate tasks, so it would be better to scale
# with a bigger instance before resorting to SQS.

# from boto.sqs.connection import SQSConnection

# sqs_conn = ''

# This holds all the tasks.  They are pulled from this directory
# with a FIFO execution style.  The tasks are identified by the pid of
# the requesting process.  Unless the tasks really jam up and the server
# is rebooted, there's no chance of collision.
local_queue_dir = '/tmp/jsonrpc_queue'

# This holds all the temporary files for the tasks.  It is only used
# here as the root of the cleanup process.  Each task identifies its own
# tmpdir whish is the home directory for the task.   This will almost always 
# be the same as queue filename.  But there # is still the option for the 
# user to identify a specific tmpdir to run from.
jsonrpc_tmpdir = '/tmp/jsonrpc'


rpc_service = rpc_service_setup()

class JSONRPCDaemon(Daemon):
    "Daemon class for processing JSON RPC requests"

    def run_an_item(self,qfile_list):
        "Pulls an item from the queue, and sends it to the rpc_service."
        
        # Get the contents of the oldest file.
        oldest = qfile_list[0]
        oldest_time = os.stat(local_queue_dir + '/' + oldest).st_mtime
        for qf in qfile_list[1:]:
            qf_time = os.stat(local_queue_dir + '/' + qf).st_mtime
            if qf_time < oldest_time:
                oldest = qf
                oldest_time = qf_time
        oldest_fd = open(local_queue_dir + '/' + oldest,'r')
        request_str = oldest_fd.read()
        oldest_fd.close()
        ## remove the file before doing anything to make sure failures
        ## don't result in runaway executions.
        os.remove(local_queue_dir + '/' + oldest)
      
        ## Execute the request.
        try: 
            full_request = json.loads(request_str)
            # Go to the tmpdir from the request.
            tmpdir = full_request['tmpdir']
            os.chdir(tmpdir)
            # _request is a copy of the original request for debugging.
            td = open(tmpdir + '/' + '_request','w')
            td.write(request_str)
            td.close()
            # Funally pass the request to the rpc service.
            rpc_request_str = json.dumps(full_request['request'])
            result = rpc_service.call(rpc_request_str)
        except Exception:
            time.sleep(60)
            pass

    def run(self):
        "Loop forever function. Sleeps one second between queue checks."
        cleanup_count = 0
        while True:

            if not cleanup_count:
                self.do_cleanup()
            cleanup_count = (cleanup_count + 1) % 3600 
                            ## cleanup about once an hour

            ## Wait until there is a file in the local_queue_dir
            qfile_list = os.listdir(local_queue_dir)
            if len(qfile_list) == 0:
                time.sleep(1)
                continue
            self.run_an_item(qfile_list)


    def do_cleanup(self):
        "Cleans out any directories that are older than a day."
        tmpdir_list = os.listdir(jsonrpc_tmpdir)
        for d in tmpdir_list:
            dpath = jsonrpc_tmpdir + '/' + d
            mtime = os.stat(dpath).st_mtime
            if mtime + 86400 < time.time(): #older than a day
                try:
                    try:
                        shutil.rmtree(dpath)
                    except Exception:
                        os.remove(dpath);
                except Exception:
                    pass
    
        
def usage():
    print "usage: %s start|stop|restart" % sys.argv[0]
    sys.exit(2)

debug = 1

if __name__ == "__main__":

    # Run as the "apache" user. This should prevent most mischief.
    os.seteuid(48)
    # There's really no loss in running in debug mode always.
    if debug:
        open('/tmp/jsonrpc_stderr','w').close()
        open('/tmp/jsonrpc_stdout','w').close()
        daemon = JSONRPCDaemon('/tmp/jsonrpc_daemon.pid',
                stderr='/tmp/jsonrpc_stderr',stdout='/tmp/jsonrpc_stdout')
    else:
        daemon = JSONRPCDaemon('/tmp/jsonrpc_daemon.pid')
    if len(sys.argv) >= 2:
        if 'start' == sys.argv[1]:
#            if len(sys.argv) == 4:
#                key_id = sys.argv[2]
#                secret_key = sys.argv[3]
#                sqs_conn = SQSConnection(key_id,secret_key)
#            elif (os.environ.has_key('AWS_ACCESS_KEY_ID') and 
#                    os.environ.has_key('AWS_SECRET_ACCESS_KEY_ID')):    
#                key_id = os.environ['AWS_ACCESS_KEY_ID']
#                secret_key = os.environ['AWS_SECRET_ACCESS_KEY_ID']
#                sqs_conn = SQSConnection(key_id,secret_key)
            daemon.start()
        elif 'stop' == sys.argv[1]:
            daemon.stop()
        elif 'restart' == sys.argv[1]:
            daemon.restart()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s start|stop|restart" % sys.argv[0]
        sys.exit(2)
