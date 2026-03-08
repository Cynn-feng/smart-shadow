package main

import (
	"encoding/base64"
	"fmt"
	"io/ioutil"
	"log"

	"chainmaker.org/chainmaker/pb-go/v2/common"
	sdk "chainmaker.org/chainmaker/sdk-go/v2"
	"chainmaker.org/chainmaker/sdk-go/v2/utils"
)

func main() {
	fmt.Println(">>> 🚀 正在启动智影链 (Smart Shadow) 专属合约部署引擎...")

	// 初始化客户端：依赖 ./sdk_config.yml（节点与证书路径需正确）
	cc, err := sdk.NewChainClient(sdk.WithConfPath("./sdk_config.yml"))
	if err != nil {
		log.Fatalf("❌ 客户端初始化失败: %v", err)
	}
	defer cc.Stop()

	// 部署参数：合约名/版本用于链上标识；kvs 为初始化参数（可为空）
	contractName := "fact"
	version := "1.0"
	var kvs []*common.KeyValuePair

	// 读取合约压缩包：需与 runtime 匹配（此处 RuntimeType_DOCKER_GO）
	contractFilePath := "./contract/fact.7z"
	byteCode, err := ioutil.ReadFile(contractFilePath)
	if err != nil {
		log.Fatalf("❌ 读取合约文件失败: %v", err)
	}

	// byteCode 编码：此处转为 Base64 字符串作为 payload 入参
	byteCodeStr := base64.StdEncoding.EncodeToString(byteCode)

	// 构造部署 Payload：runtime 必须与合约实际运行环境一致
	payload, err := cc.CreateContractCreatePayload(
		contractName,
		version,
		byteCodeStr,
		common.RuntimeType_DOCKER_GO,
		kvs,
	)
	if err != nil {
		log.Fatalf("❌ 构造合约 Payload 失败: %v", err)
	}

	// 多管理员背书：收集各组织管理员签名，用于合约管理类交易
	var endorsements []*common.EndorsementEntry

	e1, _ := cc.SignContractManagePayload(payload)
	endorsements = append(endorsements, e1)

	e2, _ := utils.MakeEndorserWithPath(
		"./crypto-config/wx-org2.chainmaker.org/user/admin1/admin1.sign.key",
		"./crypto-config/wx-org2.chainmaker.org/user/admin1/admin1.sign.crt",
		payload,
	)
	endorsements = append(endorsements, e2)

	e3, _ := utils.MakeEndorserWithPath(
		"./crypto-config/wx-org3.chainmaker.org/user/admin1/admin1.sign.key",
		"./crypto-config/wx-org3.chainmaker.org/user/admin1/admin1.sign.crt",
		payload,
	)
	endorsements = append(endorsements, e3)

	e4, _ := utils.MakeEndorserWithPath(
		"./crypto-config/wx-org4.chainmaker.org/user/admin1/admin1.sign.key",
		"./crypto-config/wx-org4.chainmaker.org/user/admin1/admin1.sign.crt",
		payload,
	)
	endorsements = append(endorsements, e4)

	fmt.Printf(">>> 🔐 已成功收集 %d 个节点的管理员多重签名背书...\n", len(endorsements))
	fmt.Println(">>> ⏳ 正在向 4 节点共识网络广播提案并等待打包出块 (启动 DockerVM 约需 15-30 秒)...")

	// 广播部署请求：超时时间 300（与链网络/虚拟机启动耗时相关）
	resp, err := cc.SendContractManageRequest(payload, endorsements, 300, true)
	if err != nil {
		log.Fatalf("❌ 发送请求失败: %v", err)
	}

	// 回执检查：SUCCESS 表示部署交易执行成功，否则输出链端与虚拟机错误信息
	if resp.Code == common.TxStatusCode_SUCCESS {
		fmt.Printf(">>> ✅ 恭喜！智能合约 [%s] 部署成功！\n", contractName)
		fmt.Printf(">>> 🔗 部署交易 TxID: %s\n", resp.TxId)
	} else {
		fmt.Printf(">>> ❌ 合约部署失败！全局状态码: %s, 全局信息: %s\n", resp.Code.String(), resp.Message)
		if resp.ContractResult != nil {
			fmt.Printf(">>> 💔 虚拟机返回状态码: %d\n", resp.ContractResult.Code)
			fmt.Printf(">>> 💔 虚拟机错误信息: %s\n", resp.ContractResult.Message)
		}
	}
}
