import subprocess
import asyncio
import traceback
import logging
import json
import time
from log_settings import getStreamLogger
from datetime import datetime
from constants import *
from utilities import server_utils
import analyzer_process

GLOBAL_LOGGER = getStreamLogger()

'''
        Starts throughput measuring subproc instances
        one process for packet measuring (shark)
        one process for producing TCP traffic (iperf3)
        and returns both subproc objects

        @PARAMS:
            filename        : filename for network tracefile (pcapng)
            o_file          : output file for the process output

        @RETURNS:
            shark_proc      : shark process object
            throughput_proc : throughput measurer process object
'''
def start_throughput_measure(filename, o_file):
    shark_proc = None
    throughput_proc = None
    output_file = None
    try:
        shark_proc = subprocess.Popen(["tshark", "-w", filename])
        output_file = open(o_file,"w+")
        throughput_proc = subprocess.Popen(["iperf3", "-s",
                                            "--port", str(THPT_IPERF_PORT)
                                            ], stdout = output_file
                                             , stderr = output_file )
        output_file.close()
        GLOBAL_LOGGER.debug("waiting 10 seconds for shark to come online")
        time.sleep(10)
        GLOBAL_LOGGER.debug("Throughput test started")
    except:
        GLOBAL_LOGGER.error("FAILED TO START THROUGHPUT TEST")
        try:
            shark_proc.kill()
            throughput_proc.kill()
            output_file.close()
        except:
            pass
        raise
    return shark_proc, throughput_proc


'''
        Ends a shark process and throughput measuring process
        @PARAMS:
            o_file                 : filename containing the output of 
                                     throughput_proc
            mtu                    : MTU value used for result computation

        @RETURNS:
            speed_plot             : a list of plot points for plotting
                                     throughput test results
            throughput_average     : average throughput measured
            throughput_ideal       : calculated ideal throughput
            transfer_time_average  : average transfer time measured
            transfer_time_ideal    : calculated ideal transfer time
            tcp_ttr                : ratio between actual and ideal transfer time
'''
def end_throughput_measure(o_file, mtu=None):
    speed_plot = None
    throughput_average = None
    throughput_ideal = None
    transfer_time_average = None
    transfer_time_ideal = None
    tcp_ttr = None
    try:
        throughput_average, throughput_ideal, transfer_time_average, \
                transfer_time_ideal, tcp_ttr, speed_plot = \
                server_utils.parse_shark(o_file, mtu)
        GLOBAL_LOGGER.debug("throughput test done")
    except:
        GLOBAL_LOGGER.error("throughput parsing error")
        raise
    return throughput_average, throughput_ideal, transfer_time_average, \
            transfer_time_ideal, tcp_ttr, speed_plot

'''
        Wraps the entire throughput
        attainment process into one method
            This function then sends a json string containing
            the results taken from the entire throughput measurement
            process
        @PARAMS:
                websocket   :   websocket object
                path        :
'''
async def measure_throughput(websocket, path):
    throughput_mode = await websocket.recv()
    thpt_proc = None
    shark_proc = None
    # return values
    ret_dict = {}
    fname = "tempfiles/reverse_mode/thpt_temp_file"
    try:
        pcap_name = "tempfiles/reverse_mode/thpt_temp.pcap"
        server_utils.prepare_file(pcap_name)
        #output_file = open(fname,"w+")
        shark_proc, thpt_proc = start_throughput_measure(pcap_name, fname)
        await websocket.send("throughput servers up")
        await websocket.recv()
        thpt_proc.kill()
        shark_proc.kill()
        #output_file.close()
        mtu = None
        rtt = 1
        client_params = json.loads(throughput_mode)
        try:
            mtu = client_params["MTU"]
            rtt = client_params["RTT"]
        except:
            pass

        # throughput process analysis
        throughput_average, throughput_ideal, transfer_time_average, \
                transfer_time_ideal, tcp_ttr, speed_plot =\
                end_throughput_measure(fname, mtu)
        ret_dict["THPT_AVG"]       = throughput_average
        ret_dict["THPT_IDEAL"]     = throughput_ideal
        ret_dict["TRANSFER_AVG"]   = transfer_time_average
        ret_dict["TRANSFER_IDEAL"] = transfer_time_ideal
        ret_dict["TCP_TTR"]        = tcp_ttr
        ret_dict["SPEED_PLOT"]     = speed_plot

        server_ip = client_params["SERVER_IP"]
        # pcap metrics analyzer
        # efficiency
        transmitted_bytes, retransmitted_bytes, tcp_efficiency = \
                analyzer_process.analyze_efficiency(pcap_name, server_ip)
        ret_dict["TRANS_BYTES"] = transmitted_bytes
        ret_dict["RETX_BYTES"]  = retransmitted_bytes
        ret_dict["TCP_EFF"]     = tcp_efficiency

        client_ip = websocket.remote_address[0]
        # buffer delay
        average_rtt, buffer_delay =\
                analyzer_process.analyze_buffer_delay\
                (pcap_name, server_ip, client_ip, rtt)
        ret_dict["AVE_RTT"]   = average_rtt
        ret_dict["BUF_DELAY"] = buffer_delay

    except:
        try:
            thpt_proc.kill()
            shark_proc.kill()
        except:
            pass
        # MOVE FILES FOR FUTURE DEBUGGING
        debug_file = datetime.today().strftime('tempfiles/reverse_mode/%Y-%m-%d-%H-%M-%S.log')
        server_utils.save_tempfile(fname, debug_file)
        traceback.print_exc()
        GLOBAL_LOGGER.error("throughput test failed")
    try:
        await websocket.send(json.dumps(ret_dict))
    except:
        try:
            output_file = open(fname,"a")
            traceback.print_exc(file=output_file)
            output_file.close()
        except:
            pass
        await websocket.close()
    # done

