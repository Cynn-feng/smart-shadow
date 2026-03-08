import sys
import json
import torch
import numpy as np
import cv2
from PIL import Image, ImageFile
from ultralytics import YOLO
from scipy.spatial.distance import cosine
import warnings
import os

warnings.filterwarnings("ignore")
ImageFile.LOAD_TRUNCATED_IMAGES = True
# HuggingFace 镜像源：在网络受限环境下加速/稳定模型下载
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

try:
    from transformers import CLIPProcessor, CLIPModel, pipeline
except ImportError:
    print(
        json.dumps({"error": "Missing library. Please run: pip install transformers"})
    )
    sys.exit(1)


# cv2 安全读取：兼容包含中文路径/特殊字符的文件名
def cv2_imread_safe(file_path):
    try:
        return cv2.imdecode(np.fromfile(file_path, dtype=np.uint8), -1)
    except Exception:
        return None


# 模块 1：AIGC 侦测器（优先读元数据，失败再走模型推理）
class AIGCDetector:
    _pipeline = None

    def __init__(self):
        pass

    def _load_model(self):
        if AIGCDetector._pipeline is not None:
            return
        try:
            print("正在加载 AIGC 检测模型...", file=sys.stderr)
            self._pipeline = pipeline(
                "image-classification", model="umm-maybe/AI-image-detector"
            )
            AIGCDetector._pipeline = self._pipeline
        except Exception as e:
            raise RuntimeError(f"Failed to load AIGC model: {e}")

    def detect(self, img_path):
        result = {"is_aigc": False, "score": 0, "reason": "Natural Distribution"}
        try:
            pil_img = Image.open(img_path).convert("RGB")
            info = pil_img.info

            # 元数据快速命中：常见生成工具会在图片信息中写入参数/软件标识
            if "parameters" in info and (
                "Steps: " in info["parameters"]
                or "Sampler: " in info.get("parameters", "")
            ):
                return {"is_aigc": True, "score": 99, "reason": "Stable Diffusion Meta"}
            if "Software" in info and (
                "Midjourney" in info["Software"] or "Niji" in info.get("Software", "")
            ):
                return {"is_aigc": True, "score": 99, "reason": "Midjourney Meta"}

            self._load_model()
            preds = self._pipeline(pil_img)

            ai_score = 0.0
            human_score = 0.0

            # 兼容不同标签集合：将模型输出聚合到 AI/Human 两类分数
            for p in preds:
                if p["label"] in ["artificial", "AI", "fake"]:
                    ai_score = p["score"]
                elif p["label"] in ["human", "real"]:
                    human_score = p["score"]

            final_score = int(ai_score * 100)
            if final_score > 50:
                result["is_aigc"] = True
                result["score"] = final_score
                result["reason"] = f"AI Model Confidence: {final_score}%"
            else:
                result["is_aigc"] = False
                result["score"] = final_score
                result["reason"] = f"Human Art Confidence: {int(human_score * 100)}%"
        except Exception as e:
            result["reason"] = f"Detection Error: {str(e)}"
        return result


# 模块 2：版权指纹提取器（CLIP 多区域切片 + YOLO 主体识别）
class CopyrightAlgo:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CopyrightAlgo, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, device=None):
        if self._initialized:
            return
        self.device = self._select_device(device)
        self.yolo = None
        self.clip_model = None
        self.clip_processor = None
        self.clip_model_name = "openai/clip-vit-base-patch32"
        self._load_models()
        self._initialized = True

    @staticmethod
    def _select_device(device=None):
        # 设备选择优先级：手动指定 > CUDA > MPS > CPU
        if device:
            return torch.device(device)
        if torch.cuda.is_available():
            return torch.device("cuda")
        try:
            if torch.backends.mps.is_available():
                return torch.device("mps")
        except:
            pass
        return torch.device("cpu")

    def _load_models(self):
        self.yolo = YOLO("yolov8n.pt")
        print(f"正在加载 CLIP 模型 ({self.clip_model_name})...", file=sys.stderr)
        self.clip_model = CLIPModel.from_pretrained(self.clip_model_name).to(
            self.device
        )
        self.clip_processor = CLIPProcessor.from_pretrained(self.clip_model_name)
        self.clip_model.eval()

    def get_feature_vector(self, img_path):
        result = {"main_object": "unknown", "vector": []}
        try:
            print(">>> [DEBUG] 开始对图片进行 6 维裂变切片...", flush=True)
            img = Image.open(img_path).convert("RGB")
            w, h = img.size

            # 将图片拆为 6 个区域：全图/四象限/中心区域，用于增强对裁剪与截图的鲁棒性
            regions = [
                img,  # 全图
                img.crop((0, 0, w // 2, h // 2)),  # 左上
                img.crop((w // 2, 0, w, h // 2)),  # 右上
                img.crop((0, h // 2, w // 2, h)),  # 左下
                img.crop((w // 2, h // 2, w, h)),  # 右下
                img.crop(
                    (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
                ),  # 中心
            ]

            # CLIP 批处理：一次性提取 6 张图的特征
            inputs = self.clip_processor(images=regions, return_tensors="pt").to(
                self.device
            )
            with torch.no_grad():
                feats = self.clip_model.get_image_features(**inputs)

                # 兼容 transformers 不同返回类型：统一转换为 torch.Tensor
                if not isinstance(feats, torch.Tensor):
                    if (
                        hasattr(feats, "image_embeds")
                        and feats.image_embeds is not None
                    ):
                        feats = feats.image_embeds
                    elif (
                        hasattr(feats, "pooler_output")
                        and feats.pooler_output is not None
                    ):
                        feats = feats.pooler_output
                    elif isinstance(feats, tuple):
                        feats = feats[0]

                # 若输出为更高维结构，取第 0 token/主向量
                if feats.dim() > 2:
                    feats = feats[:, 0, :]

                # 若不是 512 维且存在投影层，则投影到标准 512 维空间
                if feats.shape[-1] != 512 and hasattr(
                    self.clip_model, "visual_projection"
                ):
                    feats = self.clip_model.visual_projection(feats)

                # 归一化后展平为 3072 维（6 * 512）
                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                all_feats_flat = feats.cpu().numpy().flatten().tolist()

            result["vector"] = [round(float(x), 5) for x in all_feats_flat]
            print(
                f">>> [DEBUG] ✅ 裂变提取成功！总向量长度: {len(result['vector'])}",
                flush=True,
            )

            # YOLO：辅助给出主目标类别（用于展示/标签，不参与向量计算）
            yolo_res = self.yolo.predict(img_path, verbose=False, conf=0.25)[0]
            boxes = yolo_res.boxes
            if boxes and len(boxes) > 0:
                best_idx = int(np.argmax(boxes.conf.cpu().numpy()))
                cls_id = int(boxes.cls[best_idx])
                result["main_object"] = yolo_res.names[cls_id]
            else:
                result["main_object"] = "General Scene"

        except Exception as e:
            print("\n======================================", flush=True)
            print("❌ [致命错误] 指纹提取崩溃了！原因如下：", flush=True)
            import traceback

            traceback.print_exc()
            print("======================================\n", flush=True)
            result["error"] = str(e)
            result["vector"] = [0.0] * 512

        return result
        result = {"main_object": "unknown", "vector": []}
        try:
            print(">>> [DEBUG] 开始对图片进行 6 维裂变切片...", flush=True)
            img = Image.open(img_path).convert("RGB")
            w, h = img.size

            regions = [
                img,  # 全图
                img.crop((0, 0, w // 2, h // 2)),  # 左上
                img.crop((w // 2, 0, w, h // 2)),  # 右上
                img.crop((0, h // 2, w // 2, h)),  # 左下
                img.crop((w // 2, h // 2, w, h)),  # 右下
                img.crop(
                    (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
                ),  # 中心
            ]

            inputs = self.clip_processor(images=regions, return_tensors="pt").to(
                self.device
            )
            with torch.no_grad():
                feats = self.clip_model.get_image_features(**inputs)

                # 兼容不同返回类型：统一转换为 torch.Tensor，并在需要时投影到 512 维
                if not isinstance(feats, torch.Tensor):
                    if hasattr(feats, "pooler_output"):
                        feats = feats.pooler_output
                        if hasattr(self.clip_model, "visual_projection"):
                            feats = self.clip_model.visual_projection(feats)
                    elif hasattr(feats, "image_embeds"):
                        feats = feats.image_embeds
                    elif isinstance(feats, tuple):
                        feats = feats[0]

                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                all_feats_flat = feats.cpu().numpy().flatten().tolist()

            result["vector"] = [round(float(x), 5) for x in all_feats_flat]
            print(
                f">>> [DEBUG] ✅ 裂变提取成功！总向量长度: {len(result['vector'])}",
                flush=True,
            )

            yolo_res = self.yolo.predict(img_path, verbose=False, conf=0.25)[0]
            boxes = yolo_res.boxes
            if boxes and len(boxes) > 0:
                best_idx = int(np.argmax(boxes.conf.cpu().numpy()))
                cls_id = int(boxes.cls[best_idx])
                result["main_object"] = yolo_res.names[cls_id]
            else:
                result["main_object"] = "General Scene"

        except Exception as e:
            print("\n======================================", flush=True)
            print("❌ [致命错误] 指纹提取崩溃了！原因如下：", flush=True)
            import traceback

            traceback.print_exc()
            print("======================================\n", flush=True)
            result["error"] = str(e)
            result["vector"] = [0.0] * 512

        return result
        result = {"main_object": "unknown", "vector": []}
        try:
            print(">>> [DEBUG] 开始对图片进行 6 维裂变切片...", flush=True)
            img = Image.open(img_path).convert("RGB")
            w, h = img.size

            regions = [
                img,  # 全图
                img.crop((0, 0, w // 2, h // 2)),  # 左上
                img.crop((w // 2, 0, w, h // 2)),  # 右上
                img.crop((0, h // 2, w // 2, h)),  # 左下
                img.crop((w // 2, h // 2, w, h)),  # 右下
                img.crop(
                    (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
                ),  # 中心
            ]

            inputs = self.clip_processor(images=regions, return_tensors="pt").to(
                self.device
            )
            with torch.no_grad():
                feats = self.clip_model.get_image_features(**inputs)
                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                all_feats_flat = feats.cpu().numpy().flatten().tolist()

            result["vector"] = [round(float(x), 5) for x in all_feats_flat]
            print(
                f">>> [DEBUG] ✅ 裂变提取成功！总向量长度: {len(result['vector'])}",
                flush=True,
            )

            yolo_res = self.yolo.predict(img_path, verbose=False, conf=0.25)[0]
            boxes = yolo_res.boxes
            if boxes and len(boxes) > 0:
                best_idx = int(np.argmax(boxes.conf.cpu().numpy()))
                cls_id = int(boxes.cls[best_idx])
                result["main_object"] = yolo_res.names[cls_id]
            else:
                result["main_object"] = "General Scene"

        except Exception as e:
            print("\n======================================", flush=True)
            print("❌ [致命错误] 指纹提取崩溃了！原因如下：", flush=True)
            import traceback

            traceback.print_exc()
            print("======================================\n", flush=True)

            result["error"] = str(e)
            result["vector"] = [0.0] * 512

        return result
        result = {"main_object": "unknown", "vector": []}
        try:
            img = Image.open(img_path).convert("RGB")
            w, h = img.size

            regions = [
                img,  # 全图
                img.crop((0, 0, w // 2, h // 2)),  # 左上
                img.crop((w // 2, 0, w, h // 2)),  # 右上
                img.crop((0, h // 2, w // 2, h)),  # 左下
                img.crop((w // 2, h // 2, w, h)),  # 右下
                img.crop(
                    (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
                ),  # 中心核心
            ]

            all_feats_flat = []
            for region in regions:
                inputs = self.clip_processor(images=region, return_tensors="pt").to(
                    self.device
                )
                with torch.no_grad():
                    feat = self.clip_model.get_image_features(**inputs)
                    feat = feat / feat.norm(p=2, dim=-1, keepdim=True)
                    # 多区域指纹拼接：将 6 组特征展开为一个长向量
                    all_feats_flat.extend(feat.cpu().numpy().flatten().tolist())

            result["vector"] = [round(float(x), 5) for x in all_feats_flat]

            yolo_res = self.yolo.predict(img_path, verbose=False, conf=0.25)[0]
            boxes = yolo_res.boxes
            if boxes and len(boxes) > 0:
                best_idx = int(np.argmax(boxes.conf.cpu().numpy()))
                cls_id = int(boxes.cls[best_idx])
                result["main_object"] = yolo_res.names[cls_id]
            else:
                result["main_object"] = "General Scene"

        except Exception as e:
            result["error"] = str(e)
            result["vector"] = [0.0] * 512

        return result

    # compare_vectors：余弦相似度（输出 0~100 的百分比）
    def compare_vectors(self, vec1, vec2):
        try:
            if not vec1 or not vec2:
                return 0.0
            v1 = np.array(vec1, dtype=float)
            v2 = np.array(vec2, dtype=float)
            dist = cosine(v1, v2)
            similarity = 1 - dist
            return round(max(0.0, similarity) * 100, 2)
        except:
            return 0.0


if __name__ == "__main__":
    # CLI：mode=extract 时输出 AIGC 判定 + 特征向量（JSON）
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: script.py [mode] [path]"}))
        sys.exit(1)

    mode, img_path = sys.argv[1], sys.argv[2]
    if not os.path.exists(img_path):
        print(json.dumps({"error": f"File not found: {img_path}"}))
        sys.exit(1)

    detector = AIGCDetector()
    algo = CopyrightAlgo()

    if mode == "extract":
        ai_res = detector.detect(img_path)
        feat_res = algo.get_feature_vector(img_path)
        print(
            json.dumps(
                {
                    "is_aigc": ai_res["is_aigc"],
                    "aigc_score": ai_res["score"],
                    "aigc_reason": ai_res["reason"],
                    "main_object": feat_res.get("main_object", "unknown"),
                    "feature_vector": feat_res.get("vector", []),
                }
            )
        )
