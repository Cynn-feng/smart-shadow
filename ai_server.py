from fastapi import FastAPI, File, UploadFile
import uvicorn
import shutil
import os
import faiss
import numpy as np
import pickle
from pydantic import BaseModel
from super_algo import AIGCDetector, CopyrightAlgo

app = FastAPI()

# 启动预热：提前加载模型与向量引擎，避免首个请求延迟过高
print(">>> 正在预加载 AI 模型与 Faiss 向量引擎，请稍候...", flush=True)
detector = AIGCDetector()
detector.detect("test_placeholder.jpg")
algo = CopyrightAlgo()


class FaissManager:
    # Faiss 向量库：Index + CID 元数据持久化到本地文件
    def __init__(self, dim=512, index_file="faiss.index", meta_file="faiss_meta.pkl"):
        self.dim = dim
        self.index_file = index_file
        self.meta_file = meta_file
        self.cids = []

        if os.path.exists(index_file) and os.path.exists(meta_file):
            self.index = faiss.read_index(index_file)
            with open(meta_file, "rb") as f:
                self.cids = pickle.load(f)
            print(
                f">>> ✅ Faiss 引擎加载成功，库中共有 {self.index.ntotal} 个特征切片。"
            )
        else:
            self.index = faiss.IndexFlatIP(dim)
            print(">>> ⚠️ Faiss 为空，已创建全新库。")

    def add_vector(self, cid: str, vector: list):
        # 写入向量并同步更新元数据（CID 列表）
        vec_np = np.array([vector], dtype=np.float32)
        self.index.add(vec_np)
        self.cids.append(cid)
        faiss.write_index(self.index, self.index_file)
        with open(self.meta_file, "wb") as f:
            pickle.dump(self.cids, f)

    def search_vector(self, vector: list, top_k=1):
        # 空库直接返回；相似度使用内积并转换为百分比展示
        if self.index.ntotal == 0:
            return None, 0.0
        vec_np = np.array([vector], dtype=np.float32)
        distances, indices = self.index.search(vec_np, top_k)
        best_idx = indices[0][0]
        best_sim = distances[0][0]
        if best_idx != -1 and best_idx < len(self.cids):
            sim_percent = min(round(float(best_sim) * 100, 2), 100.0)
            return self.cids[best_idx], sim_percent
        return None, 0.0


faiss_db = FaissManager()
print(">>> ✅ AI 服务就绪！", flush=True)


class VectorItem(BaseModel):
    # CID：通常为 IPFS CID；vector：特征数组（可能为多段拼接）
    cid: str
    vector: list


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    # 上传文件落盘：供 detector/algo 读取；finally 中确保清理临时文件
    temp_path = f"temp_api_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        ai_res = detector.detect(temp_path)
        feat_res = algo.get_feature_vector(temp_path)
        return {
            "is_aigc": ai_res["is_aigc"],
            "aigc_score": ai_res["score"],
            "aigc_reason": ai_res["reason"],
            "main_object": feat_res.get("main_object", "unknown"),
            "feature_vector": feat_res.get("vector", []),
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/add_vector")
async def add_vector(item: VectorItem):
    vec = item.vector
    dim = faiss_db.dim
    # 多段指纹入库：当 vector 为 dim 的整倍数时，按 dim 切片分别写入
    if len(vec) % dim == 0 and len(vec) > 0:
        chunks = len(vec) // dim
        for i in range(chunks):
            sub_vec = vec[i * dim : (i + 1) * dim]
            faiss_db.add_vector(item.cid, sub_vec)
    else:
        faiss_db.add_vector(item.cid, vec)

    print(
        f">>> ✅ 成功！图片裂变为 {chunks if len(vec) % dim == 0 else 1} 个独立指纹入库，当前总容量: {faiss_db.index.ntotal}",
        flush=True,
    )
    return {
        "status": "success",
        "msg": "多维切片已入库",
        "total": faiss_db.index.ntotal,
    }


@app.post("/search")
async def search(file: UploadFile = File(...)):
    # 查询流程：提取当前向量（可能多段）→ 分段检索 → 取最高相似度与对应 CID
    temp_path = f"temp_api_search_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        current_feat = algo.get_feature_vector(temp_path)
        vec = current_feat.get("vector", [])
        ai_res = detector.detect(temp_path)

        dim = faiss_db.dim
        best_sim = 0.0
        best_cid = ""

        if len(vec) % dim == 0 and len(vec) > 0:
            chunks = len(vec) // dim
            for i in range(chunks):
                sub_vec = vec[i * dim : (i + 1) * dim]
                matched_cid, sim = faiss_db.search_vector(sub_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_cid = matched_cid

        return {
            "similarity": best_sim,
            "matched_cid": best_cid if best_cid else "",
            "current_info": {
                "is_aigc": ai_res["is_aigc"],
                "ai_score": ai_res["score"],
                "ai_reason": ai_res["reason"],
                "ai_object": current_feat.get("main_object", "unknown"),
            },
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    # 本地开发启动：监听 127.0.0.1:5000
    uvicorn.run(app, host="127.0.0.1", port=5000)
