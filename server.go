package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"io/ioutil"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/go-sql-driver/mysql"
	"golang.org/x/crypto/bcrypt"
)

var db *sql.DB

// History：用于历史记录返回（与 upload_histories 表字段对应）
type History struct {
	Id       int
	Username string
	IpfsCid  string
	TxId     string
	FileName string
	Time     string
	IsAigc   bool
	Note     string
	AiObject string
}

// Python AI 服务返回结构：提取 AIGC 判定与特征向量
type PyExtractResp struct {
	IsAigc        bool      `json:"is_aigc"`
	AigcScore     int       `json:"aigc_score"`
	AigcReason    string    `json:"aigc_reason"`
	MainObject    string    `json:"main_object"`
	FeatureVector []float64 `json:"feature_vector"`
}

// Python AI 服务返回结构：相似度检索结果 + 当前图片信息
type PySearchResp struct {
	Similarity  float64 `json:"similarity"`
	MatchedCid  string  `json:"matched_cid"`
	CurrentInfo struct {
		IsAigc   bool   `json:"is_aigc"`
		AiObject string `json:"ai_object"`
	} `json:"current_info"`
}

type AuthRequest struct {
	Username string `form:"username" json:"username" binding:"required"`
	Password string `form:"password" json:"password" binding:"required"`
}

// initDB：初始化 MySQL 连接（dsn 中包含库名/字符集/时区参数）
func initDB() {
	var err error
	dsn := "root:123456@tcp(127.0.0.1:3306)/smart_shadow?charset=utf8mb4&parseTime=True&loc=Local"
	db, err = sql.Open("mysql", dsn)
	if err != nil {
		log.Fatal("数据库连接失败:", err)
	}
	if err := db.Ping(); err != nil {
		log.Fatal("数据库无法访问:", err)
	}
	fmt.Println(">>> MySQL 数据库连接成功")
}

// callPythonExtract：上传图片到 AI 服务 /extract，返回判定与特征向量
func callPythonExtract(filename string) (PyExtractResp, error) {
	var extractRes PyExtractResp
	url := "http://127.0.0.1:5000/extract"
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	file, err := os.Open(filename)
	if err != nil {
		return extractRes, err
	}
	defer file.Close()

	part, _ := writer.CreateFormFile("file", filepath.Base(filename))
	io.Copy(part, file)
	writer.Close()

	req, _ := http.NewRequest("POST", url, body)
	req.Header.Set("Content-Type", writer.FormDataContentType())

	client := &http.Client{Timeout: 45 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return extractRes, fmt.Errorf("连接AI服务失败: %v", err)
	}
	defer resp.Body.Close()

	respBytes, _ := ioutil.ReadAll(resp.Body)
	json.Unmarshal(respBytes, &extractRes)
	return extractRes, nil
}

// callPythonAddVector：将 CID 与向量写入 AI 向量库（Faiss）
func callPythonAddVector(cid string, vector []float64) error {
	url := "http://127.0.0.1:5000/add_vector"
	data := map[string]interface{}{"cid": cid, "vector": vector}
	jsonData, _ := json.Marshal(data)

	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		bodyBytes, _ := ioutil.ReadAll(resp.Body)
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(bodyBytes))
	}
	return nil
}

// callPythonSearch：上传图片到 AI 服务 /search，返回最高相似度与匹配 CID
func callPythonSearch(filename string) (PySearchResp, error) {
	var searchRes PySearchResp
	url := "http://127.0.0.1:5000/search"
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	file, err := os.Open(filename)
	if err != nil {
		return searchRes, err
	}
	defer file.Close()

	part, _ := writer.CreateFormFile("file", filepath.Base(filename))
	io.Copy(part, file)
	writer.Close()

	req, _ := http.NewRequest("POST", url, body)
	req.Header.Set("Content-Type", writer.FormDataContentType())

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return searchRes, fmt.Errorf("AI搜索失败: %v", err)
	}
	defer resp.Body.Close()

	respBytes, _ := ioutil.ReadAll(resp.Body)
	json.Unmarshal(respBytes, &searchRes)
	return searchRes, nil
}

// uploadToIPFS：调用本机 ipfs add -Q 返回 CID（需确保 ipfs daemon 已启动）
func uploadToIPFS(filename string) (string, error) {
	cmd := exec.Command("ipfs", "add", "-Q", filename)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("IPFS上传失败: %v, 输出: %s", err, string(out))
	}
	cid := strings.TrimSpace(string(out))
	return cid, nil
}

// HashPassword/CheckPasswordHash：bcrypt 处理用户密码
func HashPassword(password string) (string, error) {
	bytes, err := bcrypt.GenerateFromPassword([]byte(password), 10)
	return string(bytes), err
}

func CheckPasswordHash(password, hash string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
	return err == nil
}

func main() {
	// 启动前置：初始化 DB 与区块链客户端
	initDB()
	InitChainClient()

	r := gin.Default()
	r.LoadHTMLGlob("templates/*")
	r.Static("/static", "./static")
	r.MaxMultipartMemory = 20 << 20

	// 页面路由：落地页/登录页/工作台
	r.GET("/", func(c *gin.Context) { c.HTML(200, "landing.html", nil) })
	r.GET("/login", func(c *gin.Context) { c.HTML(200, "login.html", nil) })
	r.GET("/dashboard", func(c *gin.Context) { c.HTML(200, "dashboard.html", nil) })

	// 登录：校验用户存在与密码（兼容历史明文与 bcrypt 哈希）
	r.POST("/api/login", func(c *gin.Context) {
		var req AuthRequest
		if err := c.ShouldBind(&req); err != nil {
			c.JSON(400, gin.H{"status": "error", "msg": "缺少用户名或密码"})
			return
		}

		var dbPass string
		err := db.QueryRow("SELECT password FROM users WHERE username = ?", req.Username).Scan(&dbPass)
		if err != nil {
			if err == sql.ErrNoRows {
				c.JSON(401, gin.H{"status": "error", "msg": "用户不存在，请先注册"})
				return
			}
			c.JSON(500, gin.H{"status": "error", "msg": "数据库异常"})
			return
		}

		isMatch := false
		if strings.HasPrefix(dbPass, "$2a$") {
			isMatch = CheckPasswordHash(req.Password, dbPass)
		} else {
			isMatch = (dbPass == req.Password)
		}

		if isMatch {
			c.JSON(200, gin.H{"status": "success", "msg": "登录成功", "user": req.Username})
		} else {
			c.JSON(401, gin.H{"status": "error", "msg": "密码错误"})
		}
	})

	// 注册：bcrypt 加密后写入 users 表（用户名重复会返回失败）
	r.POST("/api/signup", func(c *gin.Context) {
		var req AuthRequest
		if err := c.ShouldBind(&req); err != nil {
			c.JSON(400, gin.H{"status": "error", "msg": "缺少用户名或密码"})
			return
		}

		hashPass, err := HashPassword(req.Password)
		if err != nil {
			c.JSON(500, gin.H{"status": "error", "msg": "密码加密失败"})
			return
		}

		_, err = db.Exec("INSERT INTO users (username, password, role) VALUES (?, ?, 'user')", req.Username, hashPass)
		if err != nil {
			c.JSON(500, gin.H{"status": "error", "msg": "注册失败，该用户名可能已被占用"})
			return
		}
		c.JSON(200, gin.H{"status": "success", "msg": "注册成功，请登录"})
	})

	// register：上传作品 → 并发执行 AI 提取与 IPFS 上传 → 合约存证 → DB 落库 → Faiss 入库
	r.POST("/register", func(c *gin.Context) {
		username := c.PostForm("username")
		note := c.PostForm("note")
		file, err := c.FormFile("image")
		if err != nil {
			c.JSON(400, gin.H{"error": "请上传图片"})
			return
		}

		tempPath := "./uploads/" + file.Filename
		os.MkdirAll("./uploads", 0755)
		c.SaveUploadedFile(file, tempPath)

		// 并发：AI 提取与 IPFS 上传互不依赖，减少接口等待时间
		var wg sync.WaitGroup
		var aiRes PyExtractResp
		var aiErr error
		var cid string
		var ipfsErr error

		wg.Add(2)
		go func() {
			defer wg.Done()
			aiRes, aiErr = callPythonExtract(tempPath)
		}()
		go func() {
			defer wg.Done()
			cid, ipfsErr = uploadToIPFS(tempPath)
		}()
		wg.Wait()

		if aiErr != nil {
			c.JSON(500, gin.H{"error": "AI分析失败: " + aiErr.Error()})
			return
		}
		if ipfsErr != nil {
			c.JSON(500, gin.H{"error": "IPFS存储失败: " + ipfsErr.Error()})
			return
		}

		// 幂等：同一 CID 若已存在历史记录，直接返回旧 tx 并补齐向量库（避免漏写）
		var count int
		db.QueryRow("SELECT count(*) FROM upload_histories WHERE ipfs_cid=?", cid).Scan(&count)
		if count > 0 {
			var oldTx string
			db.QueryRow("SELECT tx_id FROM upload_histories WHERE ipfs_cid=?", cid).Scan(&oldTx)

			callPythonAddVector(cid, aiRes.FeatureVector)

			c.JSON(200, gin.H{"status": "repeat_self", "tx_id": oldTx, "is_aigc": aiRes.IsAigc})
			return
		}

		// 链上存证：向量写入 content 字段（JSON 字符串）以便链上固化与可追溯
		vecBytes, _ := json.Marshal(aiRes.FeatureVector)
		txId, err := InvokeContract("save_evidence", cid, string(vecBytes), note)
		if err != nil {
			// 合约侧重复拦截：出现已存在/执行失败时按重复处理，并补齐向量库
			if strings.Contains(err.Error(), "already exists") || strings.Contains(err.Error(), "CONTRACT_FAIL") {
				callPythonAddVector(cid, aiRes.FeatureVector)
				c.JSON(200, gin.H{"status": "repeat_self", "tx_id": "已在链上确权(底层拦截)", "is_aigc": aiRes.IsAigc})
				return
			}
			c.JSON(500, gin.H{"error": "上链失败: " + err.Error()})
			return
		}

		stmt, err := db.Prepare("INSERT INTO upload_histories(username, ipfs_cid, tx_id, file_name, time, is_aigc, note, ai_object) VALUES(?,?,?,?,?,?,?,?)")
		if err != nil {
			c.JSON(500, gin.H{"error": "本地数据库准备失败: " + err.Error()})
			return
		}
		defer stmt.Close()

		nowStr := time.Now().Format("2006-01-02 15:04:05")
		_, err = stmt.Exec(username, cid, txId, file.Filename, nowStr, aiRes.IsAigc, note, aiRes.MainObject)
		if err != nil {
			c.JSON(500, gin.H{"error": "本地数据库写入失败: " + err.Error()})
			return
		}

		// 向量库入库：用于后续 /check 的相似度检索
		callPythonAddVector(cid, aiRes.FeatureVector)

		c.JSON(200, gin.H{
			"status":    "success",
			"tx_id":     txId,
			"ipfs_cid":  cid,
			"is_aigc":   aiRes.IsAigc,
			"ai_object": aiRes.MainObject,
			"score":     aiRes.AigcScore,
		})
	})

	// check：上传疑似图 → IPFS CID → AI 相似度检索 → 与精确 CID 匹配融合输出
	r.POST("/check", func(c *gin.Context) {
		file, _ := c.FormFile("image")
		tempPath := "./uploads/check_" + file.Filename
		os.MkdirAll("./uploads", 0755)
		c.SaveUploadedFile(file, tempPath)

		cid, _ := uploadToIPFS(tempPath)
		searchRes, err := callPythonSearch(tempPath)
		if err != nil {
			c.JSON(500, gin.H{"error": "AI检索失败: " + err.Error()})
			return
		}

		var exactCount int
		db.QueryRow("SELECT count(*) FROM upload_histories WHERE ipfs_cid=?", cid).Scan(&exactCount)

		finalSimilarity := searchRes.Similarity
		finalMatchedCid := searchRes.MatchedCid

		// 融合策略：优先 CID 精确命中；否则对特定区间相似度做映射以提升容错
		if exactCount > 0 {
			finalSimilarity = 100.0
			finalMatchedCid = cid
		} else {
			if finalSimilarity > 60.0 && finalSimilarity < 95.0 {
				finalSimilarity = finalSimilarity + ((95.0 - finalSimilarity) * 0.4)
			}
		}

		var matchedRecord History
		if finalMatchedCid != "" {
			db.QueryRow("SELECT username, tx_id, time, file_name FROM upload_histories WHERE ipfs_cid=?", finalMatchedCid).
				Scan(&matchedRecord.Username, &matchedRecord.TxId, &matchedRecord.Time, &matchedRecord.FileName)
		}

		ownerName := matchedRecord.Username
		if ownerName == "" {
			ownerName = "未知用户"
		}

		c.JSON(200, gin.H{
			"similarity":       finalSimilarity,
			"matched_cid":      finalMatchedCid,
			"matched_record":   matchedRecord,
			"current_img_info": searchRes.CurrentInfo,
			"chain_data":       gin.H{"time": time.Now().Format("2006-01-02"), "owner": ownerName},
		})
	})

	// history：按用户过滤或全量返回上传历史（用于“我的作品”页面展示）
	r.GET("/api/history", func(c *gin.Context) {
		user := c.Query("username")
		querySql := "SELECT id, username, ipfs_cid, tx_id, file_name, time, is_aigc, note FROM upload_histories ORDER BY id DESC"
		var rows *sql.Rows
		var err error

		if user != "" {
			querySql = "SELECT id, username, ipfs_cid, tx_id, file_name, time, is_aigc, note FROM upload_histories WHERE username=? ORDER BY id DESC"
			rows, err = db.Query(querySql, user)
		} else {
			rows, err = db.Query(querySql)
		}

		if err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}
		defer rows.Close()

		var list []History
		for rows.Next() {
			var h History
			err := rows.Scan(&h.Id, &h.Username, &h.IpfsCid, &h.TxId, &h.FileName, &h.Time, &h.IsAigc, &h.Note)
			if err != nil {
				continue
			}
			list = append(list, h)
		}
		c.JSON(200, gin.H{"data": list})
	})

	// tx 查询：从链上按 TxId 获取交易信息（需 ChainClient 已初始化）
	r.GET("/api/tx/:txid", func(c *gin.Context) {
		txId := c.Param("txid")
		if cc == nil {
			c.JSON(500, gin.H{"error": "区块链客户端未连接"})
			return
		}

		txInfo, err := cc.GetTxByTxId(txId)
		if err != nil {
			c.JSON(500, gin.H{"error": "查询链上数据失败: " + err.Error()})
			return
		}

		c.JSON(200, gin.H{
			"tx_id":        txInfo.Transaction.Payload.TxId,
			"block_height": txInfo.BlockHeight,
			"timestamp":    txInfo.Transaction.Payload.Timestamp,
			"gas_used":     txInfo.Transaction.Result.ContractResult.GasUsed,
			"status":       txInfo.Transaction.Result.Code.String(),
			"contract":     txInfo.Transaction.Payload.ContractName,
		})
	})

	fmt.Println(">>> 智影链 V3.0 服务启动: http://localhost:8088")
	r.Run(":8088")
}
