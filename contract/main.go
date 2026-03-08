package main

import (
	"encoding/json"
	"log"

	"chainmaker.org/chainmaker/contract-sdk-go/v2/pb/protogo"
	"chainmaker.org/chainmaker/contract-sdk-go/v2/sandbox"
	"chainmaker.org/chainmaker/contract-sdk-go/v2/sdk"
)

// FactContract 存证合约
type FactContract struct{}

// InitContract 部署时初始化入口
func (f *FactContract) InitContract() protogo.Response {
	return sdk.Success([]byte("Init fact contract success"))
}

// UpgradeContract 升级时初始化入口
func (f *FactContract) UpgradeContract() protogo.Response {
	return sdk.Success([]byte("Upgrade fact contract success"))
}

// InvokeContract 方法路由：按 method 分发到具体业务
func (f *FactContract) InvokeContract(method string) protogo.Response {
	switch method {
	case "save_evidence":
		return f.saveEvidence()
	case "query_evidence":
		return f.queryEvidence()
	default:
		return sdk.Error("invalid method")
	}
}

// saveEvidence 写入存证：同一 hash 只允许写入一次（防重复确权）
func (f *FactContract) saveEvidence() protogo.Response {
	// 入参：hash 为主键；content/note/time 为附加信息
	args := sdk.Instance.GetArgs()
	hash := string(args["hash"])       // IPFS CID
	content := string(args["content"]) // AI 特征向量（JSON 字符串）
	note := string(args["note"])       // 备注
	timeStr := string(args["time"])    // 时间戳字符串

	// 业务约束：hash 不能为空
	if hash == "" {
		return sdk.Error("hash (IPFS CID) is required")
	}

	// 幂等/防顶替：若已存在则拒绝写入
	existBytes, err := sdk.Instance.GetStateByte("fact_domain", hash)
	if err != nil {
		return sdk.Error("failed to call GetStateByte")
	}
	if len(existBytes) > 0 {
		return sdk.Error("ERROR: this evidence already exists on chain! (防篡改拦截)")
	}

	// 固化存证内容（JSON 序列化后落链）
	evidence := map[string]string{
		"hash":    hash,
		"content": content,
		"note":    note,
		"time":    timeStr,
	}
	evidenceBytes, _ := json.Marshal(evidence)

	// 写入状态数据库：key=hash，value=evidenceBytes
	err = sdk.Instance.PutStateByte("fact_domain", hash, evidenceBytes)
	if err != nil {
		return sdk.Error("failed to call PutStateByte")
	}

	// 事件：用于链外订阅/审计/异步处理
	sdk.Instance.EmitEvent("SaveEvidenceEvent", []string{hash, timeStr})

	return sdk.Success([]byte(hash))
}

// queryEvidence 按 hash 查询存证原文（JSON）
func (f *FactContract) queryEvidence() protogo.Response {
	args := sdk.Instance.GetArgs()
	hash := string(args["hash"])

	if hash == "" {
		return sdk.Error("hash is required")
	}

	// 读取存证；不存在则返回 not found
	evidenceBytes, err := sdk.Instance.GetStateByte("fact_domain", hash)
	if err != nil {
		return sdk.Error("failed to call GetStateByte")
	}
	if len(evidenceBytes) == 0 {
		return sdk.Error("evidence not found")
	}

	return sdk.Success(evidenceBytes)
}

func main() {
	err := sandbox.Start(new(FactContract))
	if err != nil {
		log.Fatal(err)
	}
}
