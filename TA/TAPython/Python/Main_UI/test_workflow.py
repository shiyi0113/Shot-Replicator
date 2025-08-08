import json
import os
import uuid
from urllib import request, parse, error
import websocket # 确保您已安装此库: pip install websocket-client

# --- 配置区 ---

# 1. ComfyUI服务器地址
SERVER_ADDRESS = "127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())

# 2. 要测试的工作流文件名
# 修改这里来选择不同的工作流
WORKFLOW_TO_TEST = "flux_canny_model_example.json" 
# WORKFLOW_TO_TEST = "AI_Camera.json" 

# --- ComfyUI API 通信函数 (精简自您的 logic.py) ---

def queue_prompt(prompt_workflow):
    """将工作流发送到ComfyUI队列并返回结果"""
    try:
        p = {"prompt": prompt_workflow, "client_id": CLIENT_ID}
        data = json.dumps(p).encode('utf-8')
        req = request.Request(f"http://{SERVER_ADDRESS}/prompt", data=data)
        response = request.urlopen(req)
        print("成功发送请求到 ComfyUI 队列。")
        return json.loads(response.read())
    except (error.URLError, ConnectionRefusedError) as e:
        print(f"\n[错误] 无法连接到 ComfyUI 服务器 ({SERVER_ADDRESS})。")
        print("请确保您的 ComfyUI 服务正在运行中。")
        exit() # 连接失败则直接退出脚本
    except Exception as e:
        print(f"[错误] 发送请求时发生未知错误: {e}")
        exit()

def get_image(filename, subfolder, folder_type):
    """从服务器下载生成的图片"""
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = parse.urlencode(data)
    with request.urlopen(f"http://{SERVER_ADDRESS}/view?{url_values}") as response:
        return response.read()

def wait_for_completion():
    """使用WebSocket等待队列执行完成"""
    print("正在通过 WebSocket 等待任务完成...")
    ws = websocket.WebSocket()
    ws.connect(f"ws://{SERVER_ADDRESS}/ws?clientId={CLIENT_ID}")
    
    while True:
        try:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                # 我们可以打印执行进度
                if message['type'] == 'progress':
                    progress = message['data']
                    print(f"进度: {progress['value']}/{progress['max']}", end='\r')
                # 当 'executing' 节点的 node 为 null 时，表示当前队列已执行完毕
                if message['type'] == 'executing' and message['data']['node'] is None:
                    print("\n任务执行完毕！")
                    break
        except websocket.WebSocketConnectionClosedException:
            print("\nWebSocket 连接已关闭。")
            break
    ws.close()

# --- 主执行逻辑 ---

if __name__ == '__main__':
    print(f"--- 开始测试 ComfyUI 工作流: {WORKFLOW_TO_TEST} ---")
    
    # 1. 加载工作流文件
    workflow_path = os.path.join(os.path.dirname(__file__), WORKFLOW_TO_TEST)
    if not os.path.exists(workflow_path):
        print(f"[错误] 找不到工作流文件: {workflow_path}")
        exit()
        
    with open(workflow_path, 'r', encoding='utf-8') as f:
        workflow = json.load(f)

    # 2. 【关键】在这里修改工作流的输入值
    #    这部分需要您根据具体工作流的内容来手动修改
    print("正在修改工作流输入...")
    if WORKFLOW_TO_TEST == "flux_canny_model_example.json":
        # 假设我们要测试Canny工作流
        # 我们需要提供一张输入图片和提示词
        
        # !! 重要提示 !!
        # 请确保这张图片在 ComfyUI 的 input 目录下
        # ComfyUI\input\your_image.png
        input_image_name = "your_image.png" # <--- 请在这里替换成您的图片文件名
        positive_prompt = "a rocket"
        
        workflow["17"]["inputs"]["image"] = input_image_name
        workflow["23"]["inputs"]["text"] = positive_prompt
        
        print(f"  - 输入图片设置为: {input_image_name}")
        print(f"  - 正面提示词设置为: {positive_prompt}")

    elif WORKFLOW_TO_TEST == "AI_Camera.json":
        # 假设我们要测试默认的文生图工作流
        positive_prompt = "a beautiful landscape"
        workflow["48"]["inputs"]["text"] = positive_prompt
        workflow["27"]["inputs"]["batch_size"] = 1 # 测试时生成1张即可
        
        print(f"  - 提示词设置为: {positive_prompt}")
        print(f"  - 生成数量设置为: 1")

    # 3. 将修改后的工作流提交到队列
    queued_data = queue_prompt(workflow)
    prompt_id = queued_data.get('prompt_id')
    if not prompt_id:
        print(f"[错误] 提交失败，返回数据: {queued_data}")
        exit()
        
    print(f"任务已成功提交, Prompt ID: {prompt_id}")

    # 4. 等待执行完成
    wait_for_completion()

    print("--- 测试结束 ---")