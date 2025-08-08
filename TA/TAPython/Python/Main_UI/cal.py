import cv2
import numpy as np
import math
import argparse
import os
from PIL import Image
from rembg import remove

# =============================================================================
# 核心功能函数 (合并自三个脚本)
# =============================================================================

def remove_background_from_image(input_image: Image.Image) -> Image.Image:
    """
    步骤 1: 从PIL图像对象中移除背景。
    :param input_image: 输入的PIL.Image对象。
    :return: 移除背景后的PIL.Image对象。
    """
    print("步骤 1/3: 正在移除图片背景...")
    try:
        # 调用rembg的核心函数remove()进行处理
        output_image = remove(input_image)
        print(" -> 背景移除成功。")
        return output_image
    except Exception as e:
        print(f"错误：移除背景时发生问题: {e}")
        raise

def analyze_image_and_get_data(image_with_alpha: Image.Image, debug_image_path=None):
    """
    步骤 2: 分析带有透明通道的图像，找到实体物体的最小面积边界框，并返回分析数据。
    :param image_with_alpha: 带有透明通道的PIL.Image对象。
    :param debug_image_path: (可选) 保存调试图像的路径。
    :return: 包含分析数据的字典。
    """
    print("步骤 2/3: 正在分析图像轮廓...")
    try:
        # 将PIL图像转换为OpenCV格式 (BGRA)
        img_np = np.array(image_with_alpha)
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGRA)

        h, w, channels = img_cv.shape
        if channels < 4:
            raise ValueError("错误：处理后的图像没有Alpha透明通道。")

        # 提取Alpha通道并创建蒙版
        alpha_channel = img_cv[:, :, 3]
        _, mask = cv2.threshold(alpha_channel, 100, 255, cv2.THRESH_BINARY)

        # 在蒙版上查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            raise ValueError("错误：在图片中没有找到任何实体轮廓。")

        # 合并所有轮廓点并计算最小面积的旋转边界框
        all_points = np.concatenate(contours, axis=0)
        rotated_rect = cv2.minAreaRect(all_points)
        
        # 提取旋转矩形信息
        center, size, angle = rotated_rect
        center_x, center_y = int(center[0]), int(center[1])
        box_w, box_h = int(size[0]), int(size[1])
        
        # 准备输出数据
        output_data = {
            "image_width": w,
            "image_height": h,
            "rotated_bounding_box": {
                "center": {"x": center_x, "y": center_y},
                "width": box_w,
                "height": box_h,
                "angle": angle,
            }
        }
        print(" -> 图像分析完成。")

        # (可选) 创建并保存调试图像
        if debug_image_path:
            print(f" -> 正在保存调试图片到: {debug_image_path}")
            box_points = np.intp(cv2.boxPoints(rotated_rect))
            debug_img_bgr = img_cv[:, :, :3].copy()
            cv2.drawContours(debug_img_bgr, [box_points], 0, (0, 255, 0), 2)
            cv2.circle(debug_img_bgr, (center_x, center_y), 5, (0, 0, 255), -1)
            cv2.imwrite(debug_image_path, debug_img_bgr)
            
        return output_data

    except Exception as e:
        print(f"错误：在分析图像时发生问题: {e}")
        raise

def calculate_ue_camera_transform(user_data: dict, analysis_data: dict):
    """
    步骤 3: 根据用户数据和图像分析数据，计算UE摄像机的位置和旋转。
    :param user_data: 包含物体3D高度和相机FOV的用户数据字典。
    :param analysis_data: 从analyze_image_and_get_data获取的分析数据字典。
    :return: 一个包含位置(location)和旋转(rotation)的元组。
    """
    print("步骤 3/3: 正在计算UE摄像机参数...")
    try:
        # --- 提取数据 ---
        object_height_3d = user_data["object_height_3d_cm"]
        camera_fov_v_deg = user_data["camera_vertical_fov_deg"]
        img_w = analysis_data["image_width"]
        img_h = analysis_data["image_height"]
        box_data = analysis_data["rotated_bounding_box"]
        box_h = box_data["height"]
        center_x = box_data["center"]["x"]
        center_y = box_data["center"]["y"]
        angle = box_data["angle"]
        
        # --- 3D数学辅助函数 ---
        def normalize(v):
            norm = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
            return (v[0] / norm, v[1] / norm, v[2] / norm) if norm != 0 else (0,0,0)

        def vec_subtract(v1, v2):
            return (v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2])

        # --- 计算距离 ---
        if box_h <= 0: raise ValueError("包围盒高度不能为零。")
        camera_fov_v_rad = math.radians(camera_fov_v_deg)
        object_angular_height_rad = (box_h / img_h) * camera_fov_v_rad
        tan_val = math.tan(object_angular_height_rad / 2.0)
        if tan_val <= 0: raise ValueError("角度计算无效，tan结果为非正数。")
        distance = (object_height_3d / 2.0) / tan_val

        # --- 计算位置 ---
        frustum_height = 2.0 * distance * math.tan(camera_fov_v_rad / 2.0)
        pixel_offset_x = center_x - (img_w / 2.0)
        pixel_offset_y = center_y - (img_h / 2.0)
        world_offset_x = (pixel_offset_x / img_h) * frustum_height
        world_offset_y = (pixel_offset_y / img_h) * frustum_height
        final_location = (-distance, -world_offset_x, -world_offset_y)

        # --- 计算旋转 ---
        target_position = (0, 0, 0)
        forward_vector = normalize(vec_subtract(target_position, final_location))
        yaw = math.degrees(math.atan2(forward_vector[1], forward_vector[0]))
        pitch = math.degrees(math.atan2(forward_vector[2], math.sqrt(forward_vector[0]**2 + forward_vector[1]**2)))
        roll = -angle
        final_rotation = (roll, pitch, yaw)

        print(" -> 参数计算完成。")
        return final_location, final_rotation

    except Exception as e:
        print(f"错误：在计算相机变换时发生问题: {e}")
        raise

# =============================================================================
# 主程序入口
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='从单张图片自动计算UE摄像机参数。',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--input', 
        type=str, 
        required=True, 
        help='输入图片的路径 (例如: rocket.jpg)。'
    )
    parser.add_argument(
        '--height', 
        type=float, 
        required=True, 
        help='物体的实际3D高度 (单位: 厘米)。'
    )
    parser.add_argument(
        '--fov', 
        type=float, 
        required=True, 
        help='UE中相机的垂直视场角 (Vertical FOV)。'
    )
    parser.add_argument(
        '--debug_image', 
        type=str, 
        default=None, 
        help='(可选) 保存分析调试图片的路径 (例如: debug_output.png)。'
    )
    
    args = parser.parse_args()

    # 检查输入文件是否存在
    if not os.path.exists(args.input):
        print(f"错误：找不到输入文件 '{args.input}'")
        exit()

    try:
        # 1. 打开原始图片
        print(f"正在读取输入图片: {args.input}")
        input_image_pil = Image.open(args.input)

        # 2. 执行完整的处理流程
        segmented_image = remove_background_from_image(input_image_pil)
        analysis_result = analyze_image_and_get_data(segmented_image, args.debug_image)
        
        user_data = {
            "object_height_3d_cm": args.height,
            "camera_vertical_fov_deg": args.fov
        }

        location, rotation = calculate_ue_camera_transform(user_data, analysis_result)

        # 3. 以清晰的格式打印最终结果
        print("\n" + "="*50)
        print("--- 最终结果：UE摄像机变换参数 ---")
        print("="*50)
        print("请将以下数值复制到UE摄像机的Transform面板中:\n")
        print(f"Location (位置):")
        print(f"    X = {location[0]:.4f}")
        print(f"    Y = {location[1]:.4f}")
        print(f"    Z = {location[2]:.4f}\n")
        
        print(f"Rotation (旋转):")
        print(f"    X (Roll)  = {rotation[0]:.4f}")
        print(f"    Y (Pitch) = {rotation[1]:.4f}")
        print(f"    Z (Yaw)   = {rotation[2]:.4f}")
        print("\n" + "="*50)

    except Exception as e:
        print(f"\n处理失败，发生错误: {e}")