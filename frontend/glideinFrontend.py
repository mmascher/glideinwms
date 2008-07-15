#!/bin/env python
#
# Description:
#   This is the main of the glideinFrontend
#
# Arguments:
#   $1 = poll period (in seconds)
#   $2 = advertize rate even if no changes (every $2 loops)
#   $3 = config file
#
# Author:
#   Igor Sfiligoi (Sept 19th 2006)
#

import signal
import os
import os.path
import sys
import fcntl
import traceback
import time
sys.path.append(os.path.join(sys.path[0],"../lib"))

import glideinFrontendInterface
import glideinFrontendLib
import logSupport

############################################################
def iterate_one(frontend_name,factory_pool,
                schedd_names,job_constraint,match_str,job_attributes,
                max_idle,reserve_idle,
                max_running,reserve_running_fraction,
                glidein_params):
    global activity_log
    glidein_dict=glideinFrontendInterface.findGlideins(factory_pool)
    condorq_dict=glideinFrontendLib.getCondorQ(schedd_names,job_constraint,job_attributes)
    condorq_dict_idle=glideinFrontendLib.getIdleCondorQ(condorq_dict)
    condorq_dict_old_idle=glideinFrontendLib.getOldCondorQ(condorq_dict_idle,600)
    condorq_dict_running=glideinFrontendLib.getRunningCondorQ(condorq_dict)

    dict_types={'idle':{'dict':condorq_dict_idle},
                'old_idle':{'dict':condorq_dict_old_idle},
                'running':{'dict':condorq_dict_running}}

    activity_log.write("Match")
    for dt in dict_types.keys():
        dict_types[dt]['count']=glideinFrontendLib.countMatch(match_str,dict_types[dt]['dict'],glidein_dict)
    

    for dt in dict_types.keys():
        total=0
        dict=dict_types[dt]['dict']
        for schedd in dict.keys():
            condorq=dict[schedd]
            condorq_data=condorq.fetchStored()
            total+=len(condorq_data.keys())
        dict_types[dt]['total']=total

    total_running=dict_types['running']['total']
    activity_log.write("Total idle %i (old %i) running %i limit %i"%(dict_types['idle']['total'],dict_types['old_idle']['total'],total_running,max_running))
    
    for glidename in dict_types['idle']['count'].keys():
        request_name=glidename
        
        count_jobs={}
        for dt in dict_types.keys():
            count_jobs[dt]=dict_types[dt]['count'][glidename]

        if total_running>=max_running:
            # have all the running jobs I wanted
            glidein_min_idle=0
        elif count_jobs['idle']>0:
            glidein_min_idle=count_jobs['idle']/3 # since it takes a few cycles to stabilize, ask for only one third
            glidein_idle_reserve=count_jobs['old_idle']/3 # do not reserve any more than the number of old idles for reserve (/3)
            if glidein_idle_reserve>reserve_idle:
                glidein_idle_reserve=reserve_idle

            glidein_min_idle+=glidein_idle_reserve
            
            if glidein_min_idle>max_idle:
                glidein_min_idle=max_idle # but never go above max
            if glidein_min_idle>(max_running-total_running+glidein_idle_reserve):
                glidein_min_idle=(max_running-total_running+glidein_idle_reserve) # don't go over the max_running
        else:
            # no idle, make sure the glideins know it
            glidein_min_idle=0 
        # we don't need more slots than number of jobs in the queue (modulo reserve)
        glidein_max_run=int((count_jobs['idle']+count_jobs['running'])*(0.99+reserve_running_fraction)+1)
        activity_log.write("For %s Idle %i (old %i) Running %i"%(glidename,count_jobs['idle'],count_jobs['old_idle'],count_jobs['running']))
        activity_log.write("Advertize %s Request idle %i max_run %i"%(request_name,glidein_min_idle,glidein_max_run))

        try:
          glidein_monitors={"Idle":count_jobs['idle'],"Running":count_jobs['running']}
          glideinFrontendInterface.advertizeWork(factory_pool,frontend_name,request_name,glidename,glidein_min_idle,glidein_max_run,glidein_params,glidein_monitors)
        except:
          warning_log.write("Advertize %s failed"%request_name)

    return

############################################################
def iterate(log_dir,sleep_time,
            frontend_name,factory_pool,
            schedd_names,job_constraint,match_str,job_attributes,
            max_idle,reserve_idle,
            max_running,reserve_running_fraction,
            glidein_params):
    global activity_log,warning_log
    startup_time=time.time()

    activity_log=logSupport.DayLogFile(os.path.join(log_dir,"frontend_info"))
    warning_log=logSupport.DayLogFile(os.path.join(log_dir,"frontend_err"))
    cleanupObj=logSupport.DirCleanup(log_dir,"(frontend_info\..*)|(frontend_err\..*)",
                                     7*24*3600,
                                     activity_log,warning_log)
    

    lock_file=os.path.join(log_dir,"frontend.lock")
    if not os.path.exists(lock_file): #create a lock file if needed
        fd=open(lock_file,"w")
        fd.close()

    fd=open(lock_file,"r+")
    try:
        fcntl.flock(fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        fd.close()
        raise RuntimeError, "Another frontend already running"
    fd.seek(0)
    fd.truncate()
    fd.write("PID: %s\nStarted: %s\n"%(os.getpid(),time.ctime(startup_time)))
    fd.flush()
    
    try:
        try:
            try:
                activity_log.write("Starting up")
                is_first=1
                while 1:
                    activity_log.write("Iteration at %s" % time.ctime())
                    try:
                        done_something=iterate_one(frontend_name,factory_pool,schedd_names,job_constraint,match_str,job_attributes,
                                                   max_idle,reserve_idle,
                                                   max_running,reserve_running_fraction,
                                                   glidein_params)
                    except KeyboardInterrupt:
                        raise # this is an exit signal, pass trough
                    except:
                        if is_first:
                            raise
                        else:
                            # if not the first pass, just warn
                            tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                                            sys.exc_info()[2])
                            warning_log.write("Exception at %s: %s" % (time.ctime(),tb))
                
                    is_first=0
                    activity_log.write("Sleep")
                    time.sleep(sleep_time)
            except KeyboardInterrupt:
                activity_log.write("Received signal...exit")
            except:
                tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                                sys.exc_info()[2])
                warning_log.write("Exception at %s: %s" % (time.ctime(),tb))
                raise
        finally:
            try:
                activity_log.write("Deadvertize my ads")
                glideinFrontendInterface.deadvertizeAllWork(factory_pool,frontend_name)
            except:
                tb = traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                                sys.exc_info()[2])
                warning_log.write("Failed to deadvertize my ads")
                warning_log.write("Exception at %s: %s" % (time.ctime(),tb))
    finally:
        fd.close()

############################################################
def main(config_file):
    config_dict={'loop_delay':60,'job_attributes':None}
    execfile(config_file,config_dict)
    iterate(config_dict['log_dir'],config_dict['loop_delay'],
            config_dict['frontend_name'],config_dict['factory_pool'],
            config_dict['schedd_names'], config_dict['job_constraint'],config_dict['match_string'],config_dict['job_attributes'],
            config_dict['max_idle_glideins_per_entry'], 5,
            config_dict['max_running_jobs'], 0.05,
            config_dict['glidein_params'])

############################################################
#
# S T A R T U P
#
############################################################

if __name__ == '__main__':
    # check that the GSI environment is properly set
    if not os.environ.has_key('X509_USER_PROXY'):
        raise RuntimeError, "Need X509_USER_PROXY to work!"
    if not os.environ.has_key('X509_CERT_DIR'):
        raise RuntimeError, "Need X509_CERT_DIR to work!"

    # make sure you use GSI for authentication
    os.environ['_CONDOR_SEC_DEFAULT_AUTHENTICATION_METHODS']='GSI'

    signal.signal(signal.SIGTERM,signal.getsignal(signal.SIGINT))
    signal.signal(signal.SIGQUIT,signal.getsignal(signal.SIGINT))
    main(sys.argv[1])
 
