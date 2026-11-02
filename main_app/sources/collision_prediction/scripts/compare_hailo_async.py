import time,threading,argparse
import cv2,numpy as np
from hailo_platform import VDevice, HailoSchedulingAlgorithm, HEF, FormatType, ConfigureParams, HailoStreamInterface, InferVStreams, InputVStreamParams, OutputVStreamParams
parser=argparse.ArgumentParser(); parser.add_argument('video'); parser.add_argument('--model',default='models/hailo8/yolo26n.hef'); args=parser.parse_args(); path=args.model; cap=cv2.VideoCapture(args.video); ok, frame=cap.read();cap.release(); assert ok
h,w=frame.shape[:2];scale=min(640/w,640/h);nw,nh=round(w*scale),round(h*scale); image=np.full((640,640,3),114,np.uint8); image[(640-nh)//2:(640-nh)//2+nh,(640-nw)//2:(640-nw)//2+nw]=cv2.cvtColor(cv2.resize(frame,(nw,nh)),cv2.COLOR_BGR2RGB)
with VDevice() as device:
 hef=HEF(path);group=device.configure(hef,ConfigureParams.create_from_hef(hef,HailoStreamInterface.PCIe))[0]
 with InferVStreams(group,InputVStreamParams.make(group,format_type=FormatType.UINT8),OutputVStreamParams.make(group,format_type=FormatType.FLOAT32)) as infer:
  with group.activate():
   sync=infer.infer({hef.get_input_vstream_infos()[0].name:image[None]})
params=VDevice.create_params();params.scheduling_algorithm=HailoSchedulingAlgorithm.ROUND_ROBIN
with VDevice(params) as device:
 model=device.create_infer_model(path)
 for out in model.outputs:out.set_format_type(FormatType.FLOAT32)
 outs={x.name:np.empty(x.shape,dtype=np.float32) for x in model.outputs}
 with model.configure() as configured:
  binding=configured.create_bindings(input_buffers={model.input_names[0]:image},output_buffers=outs)
  event=threading.Event(); errors=[]
  def callback(*,completion_info):
   errors.append(completion_info.exception);event.set()
  configured.wait_for_async_ready(timeout_ms=10000); t=time.monotonic(); job=configured.run_async([binding],callback=callback);job.wait(10000); event.wait(10); elapsed=(time.monotonic()-t)*1000
  print('EVENT',event.is_set(),'errors',errors,flush=True)
  if not event.is_set() or any(errors):raise RuntimeError('async callback failed')
  print('ASYNC_OK ms',round(elapsed,2),'diffs',[(name,round(float(np.max(np.abs(sync[name][0]-buf))),7)) for name,buf in outs.items()],flush=True)
