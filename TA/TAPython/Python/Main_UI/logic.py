# -*- coding: utf-8 -*-
import unreal
import json
import os
import subprocess
import re
import threading
import uuid
import websocket
from urllib import request, parse, error
import shutil
import tkinter as tk
from tkinter import filedialog

# 【新增】导入用于调用百度翻译API的库
import requests 
import random
import hashlib

# --- 配置区 ---
SERVER_ADDRESS = "127.0.0.1:8188"
COMFYUI_INPUT_PATH = "D:\\03_Projects\AI_Camera\ComfyUI\input" # 请务必修改这里

# --- 【请在这里填写您的百度翻译API密钥】 ---
BAIDU_APP_ID = "20241107002196612"    # 替换成您的 APP ID
BAIDU_SECRET_KEY = "wQp4jbG_Bpwl6yiObLLj" # 替换成您的密钥

# --- 文件与节点配置 ---
WORKFLOW_DEFAULT = "AI_Camera.json"
WORKFLOW_CANNY = "flux_canny_model_example.json"
NODE_ID_DEFAULT_PROMPT = "48"
NODE_ID_DEFAULT_LATENT = "27"
NODE_ID_CANNY_IMAGE_LOADER = "17"
NODE_ID_CANNY_POSITIVE_PROMPT = "23"
NODE_ID_CANNY_NEGATIVE_PROMPT = "7"
NODE_ID_CANNY_CONDITIONING = "35"
NODE_ID_CANNY_EDGE_DETECTOR = "18"
MAX_IMAGE_SLOTS = 6

# --- 路径设置 ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_IMAGE_DIR = os.path.join(CURRENT_DIR, "temp_images_comfy")
if not os.path.exists(TEMP_IMAGE_DIR):
    os.makedirs(TEMP_IMAGE_DIR)

class ShotGenerator:
    _instance = None

    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self, json_path):
        self.data = unreal.PythonBPLib.get_chameleon_data(json_path)
        if not self.data:
            raise RuntimeError(f"无法从 '{json_path}' 加载UI配置")
        
        self.ui_prompt_textbox = "prompt_textbox"
        self.ui_status_text = "status_text"
        self.ui_loading_throbber = "loading_throbber"
        self.ui_generate_button = "generate_button"
        self.ui_regenerate_button = "regenerate_button"
        self.ui_edge_image_path_text = "edge_image_path_text"
        self.ui_default_display_panel = "default_display_panel"
        self.ui_canny_display_panel = "canny_display_panel"
        self.ui_canny_input_image = "canny_input_image"
        self.ui_canny_output_image = "canny_output_image"

        self.slot_image_paths = {}
        self.edge_image_path = None
        
        unreal.log("AI镜头生成器 (ComfyUI版) UI已初始化成功")
        ShotGenerator._instance = self

    # --- ComfyUI API ---
    def _queue_prompt(self, prompt_workflow, client_id):
        p = {"prompt": prompt_workflow, "client_id": client_id}
        data = json.dumps(p).encode('utf-8')
        req = request.Request(f"http://{SERVER_ADDRESS}/prompt", data=data)
        response = request.urlopen(req)
        return json.loads(response.read())

    def _get_image(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = parse.urlencode(data)
        with request.urlopen(f"http://{SERVER_ADDRESS}/view?{url_values}") as response:
            return response.read()

    def _get_history(self, prompt_id):
        with request.urlopen(f"http://{SERVER_ADDRESS}/history/{prompt_id}") as response:
            return json.loads(response.read())
            
    # --- 【已修改】翻译功能 ---
    def _translate_if_needed(self, text):
        """如果检测到中文字符，则调用百度翻译API翻译成英文"""
        if not re.search(r'[\u4e00-\u9fa5]', text):
            return text

        unreal.log(f"检测到中文输入，正在使用百度翻译: '{text}'")

        if BAIDU_APP_ID == "YOUR_BAIDU_APP_ID" or BAIDU_SECRET_KEY == "YOUR_BAIDU_SECRET_KEY":
            unreal.log_warning("百度翻译API密钥未配置，将使用原文。")
            return text

        # --- 百度翻译API调用逻辑 ---
        api_url = 'http://api.fanyi.baidu.com/api/trans/vip/translate'
        q = text
        from_lang = 'auto'
        to_lang =  'en'
        salt = random.randint(32768, 65536)
        sign_str = BAIDU_APP_ID + q + str(salt) + BAIDU_SECRET_KEY
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        params = {
            'q': q,
            'from': from_lang,
            'to': to_lang,
            'appid': BAIDU_APP_ID,
            'salt': salt,
            'sign': sign
        }

        try:
            response = requests.get(api_url, params=params, timeout=5)
            result = response.json()
            
            if 'trans_result' in result:
                translated_text = result['trans_result'][0]['dst']
                unreal.log(f"翻译结果: '{translated_text}'")
                return translated_text
            else:
                error_msg = result.get('error_msg', '未知错误')
                unreal.log_error(f"百度翻译API返回错误: {error_msg}")
                return text # 翻译失败则返回原文

        except Exception as e:
            unreal.log_error(f"调用百度翻译API时发生网络错误: {e}. 将使用原文。")
            return text

    # --- 核心逻辑 ---
    def import_edge_image(self):
        try:
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilename(
                title="选择一张边缘检测后的图片",
                filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")]
            )
            root.destroy()
            if file_path:
                self.edge_image_path = file_path
                self.data.set_text(self.ui_edge_image_path_text, os.path.basename(self.edge_image_path))
                unreal.log(f"已导入边缘图片: {self.edge_image_path}")
            else:
                self.edge_image_path = None
                self.data.set_text(self.ui_edge_image_path_text, "未导入图片")
                unreal.log("用户取消了文件选择。")
        except Exception as e:
            unreal.log_error(f"打开文件对话框时出错: {e}")

    def generate_images(self):
        if "D:/path/to/your/ComfyUI/input" in COMFYUI_INPUT_PATH or not os.path.isdir(COMFYUI_INPUT_PATH):
            msg = "状态: 错误！请先在logic.py脚本中设置正确的COMFYUI_INPUT_PATH路径。"
            unreal.log_error(msg)
            self._update_status_on_main_thread(msg, False)
            return

        user_prompt = self.data.get_text(self.ui_prompt_textbox)
        if not user_prompt:
            self._update_status_on_main_thread("状态: 错误！请输入核心镜头描述。", False)
            return
        
        thread = threading.Thread(target=self._generate_image_thread, args=(user_prompt,))
        thread.start()

    def _generate_image_thread(self, user_prompt):
        self._set_generating_state_on_main_thread(True)
        workflow_file = ""
        try:
            client_id = str(uuid.uuid4())
            
            translated_prompt = self._translate_if_needed(user_prompt)
            
            style_prompt = " The scene is evenly lit under a bright overcast sky, showing clear details on all surfaces. Clean, minimalist composition.Architectural style photograph."
            full_prompt = f"{translated_prompt}.{style_prompt}"
            unreal.log(f"最终生成的完整提示词: {full_prompt}")

            if self.edge_image_path:
                if not os.path.exists(self.edge_image_path):
                    raise FileNotFoundError(f"导入的图片文件不存在: {self.edge_image_path}")
                
                image_filename = os.path.basename(self.edge_image_path)
                source_path = os.path.abspath(self.edge_image_path)
                destination_path = os.path.abspath(os.path.join(COMFYUI_INPUT_PATH, image_filename))

                if source_path != destination_path:
                    shutil.copy(source_path, destination_path)
                
                workflow_file = WORKFLOW_CANNY
                workflow_path = os.path.join(CURRENT_DIR, workflow_file)
                with open(workflow_path, 'r', encoding='utf-8') as f:
                    prompt_workflow = json.load(f)
                
                conditioning_node = prompt_workflow.get(NODE_ID_CANNY_CONDITIONING)
                if conditioning_node:
                    conditioning_node["inputs"]["pixels"] = [NODE_ID_CANNY_IMAGE_LOADER, 0]
                else:
                    raise ValueError(f"在工作流中找不到ID为 {NODE_ID_CANNY_CONDITIONING} 的节点。")

                prompt_workflow[NODE_ID_CANNY_IMAGE_LOADER]["inputs"]["image"] = image_filename
                prompt_workflow[NODE_ID_CANNY_POSITIVE_PROMPT]["inputs"]["text"] = full_prompt
                prompt_workflow[NODE_ID_CANNY_NEGATIVE_PROMPT]["inputs"]["text"] = "" 
            else:
                workflow_file = WORKFLOW_DEFAULT
                workflow_path = os.path.join(CURRENT_DIR, workflow_file)
                with open(workflow_path, 'r', encoding='utf-8') as f:
                    prompt_workflow = json.load(f)
                
                prompt_workflow[NODE_ID_DEFAULT_PROMPT]["inputs"]["text"] = full_prompt
                prompt_workflow[NODE_ID_DEFAULT_LATENT]["inputs"]["batch_size"] = MAX_IMAGE_SLOTS

            queued_data = self._queue_prompt(prompt_workflow, client_id)
            prompt_id = queued_data['prompt_id']

            ws = websocket.WebSocket()
            ws.connect(f"ws://{SERVER_ADDRESS}/ws?clientId={client_id}")
            while True:
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    if message['type'] == 'executing' and message['data']['node'] is None and message['data']['prompt_id'] == prompt_id:
                        break
            ws.close()

            history = self._get_history(prompt_id)[prompt_id]
            self._hide_all_image_slots_on_main_thread()
            image_index = 0
            for node_id in history['outputs']:
                node_output = history['outputs'][node_id]
                if 'images' in node_output:
                    for image_info in node_output['images']:
                        if image_index >= MAX_IMAGE_SLOTS: break
                        image_data = self._get_image(image_info['filename'], image_info['subfolder'], image_info['type'])
                        
                        temp_image_file = os.path.join(TEMP_IMAGE_DIR, f"shot_{image_index}.png")
                        with open(temp_image_file, 'wb') as f: f.write(image_data)
                        
                        if self.edge_image_path:
                            self._show_canny_result_on_main_thread(self.edge_image_path, temp_image_file)
                        else:
                            self._show_image_in_slot_on_main_thread(image_index, temp_image_file)
                        image_index += 1
            
            if image_index > 0:
                self._update_status_on_main_thread(f"状态: 成功生成 {image_index} 张图片！", False)
            else:
                self._update_status_on_main_thread("状态: 操作完成，但未找到任何输出图片。", False)

        except Exception as e:
            error_message = f"状态: AI请求失败! 错误: {e}"
            unreal.log_error(f"工作流 '{workflow_file}' 执行失败: {e}")
            self._update_status_on_main_thread(error_message, False)
        finally:
            self._set_generating_state_on_main_thread(False)

    # --- UI更新及其他辅助函数 ---
    def _run_on_main_thread(self, command):
        unreal.PythonBPLib.exec_python_command(command, True)

    def _set_generating_state_on_main_thread(self, is_generating):
        cmd = f"ai_shot_generator.logic.ShotGenerator.get_instance()._set_generating_state({is_generating})"
        self._run_on_main_thread(cmd)
        
    def _update_status_on_main_thread(self, text, is_loading):
        cmd = f"ai_shot_generator.logic.ShotGenerator.get_instance()._update_status({repr(text)}, {is_loading})"
        self._run_on_main_thread(cmd)

    def _hide_all_image_slots_on_main_thread(self):
        cmd = "ai_shot_generator.logic.ShotGenerator.get_instance()._hide_all_image_slots()"
        self._run_on_main_thread(cmd)

    def _show_image_in_slot_on_main_thread(self, index, image_path):
        cmd = f"ai_shot_generator.logic.ShotGenerator.get_instance()._show_image_in_slot({index}, {repr(image_path)})"
        self._run_on_main_thread(cmd)
        
    def _show_canny_result_on_main_thread(self, input_path, output_path):
        cmd = f"ai_shot_generator.logic.ShotGenerator.get_instance()._show_canny_result({repr(input_path)}, {repr(output_path)})"
        self._run_on_main_thread(cmd)

    def _set_generating_state(self, is_generating):
        self.data.set_visibility(self.ui_generate_button, "Collapsed")
        self.data.set_visibility(self.ui_regenerate_button, "Collapsed")
        
        status_text = "状态: 正在调用ComfyUI生成图片..." if is_generating else "状态: 操作完成"
        self._update_status(status_text, is_generating)

        if not is_generating:
            if self.slot_image_paths:
                self.data.set_visibility(self.ui_regenerate_button, "Visible")
            else:
                self.data.set_visibility(self.ui_generate_button, "Visible")

    def _update_status(self, text, is_loading):
        self.data.set_text(self.ui_status_text, text)
        self.data.set_visibility(self.ui_loading_throbber, "Visible" if is_loading else "Collapsed")

    def _hide_all_image_slots(self):
        self.data.set_visibility(self.ui_default_display_panel, "Collapsed")
        self.data.set_visibility(self.ui_canny_display_panel, "Collapsed")
        for i in range(MAX_IMAGE_SLOTS):
            self.data.set_visibility(f"image_slot_{i}", "Collapsed")
        self.data.set_visibility(self.ui_generate_button, "Visible")
        self.data.set_visibility(self.ui_regenerate_button, "Collapsed")
        self.edge_image_path = None
        self.slot_image_paths.clear()
        self.data.set_text(self.ui_edge_image_path_text, "未导入图片")

    def _show_image_in_slot(self, index, image_path):
        if index >= MAX_IMAGE_SLOTS: return
        self.data.set_visibility(self.ui_default_display_panel, "Visible")
        self.data.set_visibility(self.ui_canny_display_panel, "Collapsed")
        
        self.slot_image_paths[index] = image_path
        self.data.set_image_from_path(f"image_{index}", image_path)
        self.data.set_visibility(f"image_slot_{index}", "Visible")
        
    def _show_canny_result(self, input_path, output_path):
        self.data.set_visibility(self.ui_default_display_panel, "Collapsed")
        self.data.set_visibility(self.ui_canny_display_panel, "Visible")
        
        self.data.set_image_from_path(self.ui_canny_input_image, input_path)
        self.data.set_image_from_path(self.ui_canny_output_image, output_path)

        self.slot_image_paths.clear()
        self.slot_image_paths[0] = output_path

    def apply_shot(self, index):
        image_path = self.slot_image_paths.get(index)
        if not image_path:
            unreal.log_error(f"无法找到索引为 {index} 的图片路径！")
            return
        self._update_status(f"状态: 已选择 {os.path.basename(image_path)}，准备应用...", False)
        unreal.log(f"用户选择了图片 '{image_path}' (来自插槽 {index}) 并点击了应用。")

        if not os.path.exists(image_path):
            unreal.log_error(f"图片文件不存在: {image_path}")
            return

        unreal.log(f"开始为索引 {index} 计算镜头，使用图片: {image_path}")
        script_dir = os.path.dirname(__file__)
        batch_script_path = os.path.join(script_dir, "run_cal.bat")
        if not os.path.exists(batch_script_path):
            unreal.log_error(f"计算脚本 'run_cal.bat' 未在以下目录中找到: {script_dir}")
            return
        object_height = getattr(self, "object_height_cm", 9101.0) 
        camera_fov = getattr(self, "camera_fov", 45.0)
        command = [batch_script_path, '--input', str(image_path), '--height', str(object_height), '--fov', str(camera_fov)]
        output = ""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', startupinfo=startupinfo)
            output = result.stdout
            unreal.log("正在解析结果...")
        except subprocess.CalledProcessError as e:
            unreal.log_error(f"执行相机位置计算脚本失败。\n错误信息: {e.stderr}")
            return
        except FileNotFoundError:
            unreal.log_error(f"无法找到命令: {batch_script_path}。请确保路径正确。")
            return
        except Exception as e:
            unreal.log_error(f"调用脚本时发生未知错误: {e}")
            return
        location_data, rotation_data = None, None
        try:
            loc_match = re.search(r"Location \(位置\):\s+X = ([-.\d]+)\s+Y = ([-.\d]+)\s+Z = ([-.\d]+)", output)
            rot_match = re.search(r"Rotation \(旋转\):\s+X \(Roll\)\s*=\s*([-.\d]+)\s+Y \(Pitch\)\s*=\s*([-.\d]+)\s+Z \(Yaw)\s*=\s*([-.\d]+)", output)
            if loc_match:
                location_data = {'X': float(loc_match.group(1)), 'Y': float(loc_match.group(2)), 'Z': float(loc_match.group(3))}
            if rot_match:
                rotation_data = {'X': float(rot_match.group(1)), 'Y': float(rot_match.group(2)), 'Z': float(rot_match.group(3))}
            if not location_data or not rotation_data:
                raise ValueError("无法从输出中解析出完整的位置和旋转数据。")
        except Exception as e:
            unreal.log_error(f"解析脚本输出时出错: {e}")
            unreal.log_warning(f"接收到的原始输出:\n---\n{output}\n---")
            return
        unreal.log(f"解析成功 -> Location: {location_data}, Rotation: {rotation_data}")