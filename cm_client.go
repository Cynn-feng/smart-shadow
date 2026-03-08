package main

import (
	"fmt"
	"log"
	"time"

	"chainmaker.org/chainmaker/pb-go/v2/common"
	sdk "chainmaker.org/chainmaker/sdk-go/v2"
)

// ChainMaker 客户端：负责连接链节点并调用合约
var cc *sdk.ChainClient

// 合约名称：需与链上已部署合约名一致
const ContractName = "fact"

// InitChainClient 读取 sdk_config.yml 初始化 ChainClient，并建立连接
func InitChainClient() {
	var err error
	// sdk_config.yml 需在当前运行目录可访问（此处为 ./sdk_config.yml）
	cc, err = sdk.NewChainClient(
		sdk.WithConfPath("./sdk_config.yml"),
	)
	if err != nil {
		log.Fatalf(">>> [Error] 无法创建长安链客户端: %v\n请检查 sdk_config.yml 和证书路径是否正确！", err)
	}

	// 可选：启用证书压缩减少传输量（失败不影响主流程）
	err = cc.EnableCertHash()
	if err != nil {
		log.Printf(">>> [Warning] 证书压缩启用失败 (可能链端未开启此功能): %v", err)
	}

	fmt.Println(">>> [ChainMaker] 业务网关连接成功，正在监听合约: " + ContractName)
}

// InvokeContract 调用存证合约：methodName 为合约方法名，kvs 为入参键值对
func InvokeContract(methodName string, cid string, vectorJson string, note string) (string, error) {
	// 防御：确保 InitChainClient 已完成
	if cc == nil {
		return "", fmt.Errorf("区块链客户端未初始化")
	}

	// 参数 Key 必须与合约侧 GetArgs() 读取的 key 完全一致（hash/content/note/time）
	kvs := []*common.KeyValuePair{
		{Key: "hash", Value: []byte(cid)},           // IPFS CID
		{Key: "content", Value: []byte(vectorJson)}, // AI 向量 JSON
		{Key: "note", Value: []byte(note)},          // 备注
		{Key: "time", Value: []byte(time.Now().Format("2006-01-02 15:04:05"))}, // 业务时间戳
	}

	// 发起交易：超时参数 -1 表示使用 sdk_config.yml 的默认配置
	resp, err := cc.InvokeContract(ContractName, methodName, "", kvs, -1, true)
	if err != nil {
		return "", fmt.Errorf("上链请求网络层发送失败: %v", err)
	}

	// 回执检查：非 SUCCESS 视为链端执行失败（Message 含具体原因）
	if resp.Code != common.TxStatusCode_SUCCESS {
		return "", fmt.Errorf("链端拦截 - 状态码: %s, 详细信息: %s", resp.Code.String(), resp.Message)
	}

	fmt.Printf(">>> [Chain] 业务执行成功! 合约: %s, 方法: %s, TxId: %s\n", ContractName, methodName, resp.TxId)
	return resp.TxId, nil
}
