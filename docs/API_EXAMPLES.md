# API 使用示例

本文档提供了 SCNS-Conductor API 的详细使用示例。

## 目录

1. [基础示例](#基础示例)
2. [Python 客户端](#python-客户端)
3. [常见场景](#常见场景)
4. [错误处理](#错误处理)

## 基础示例

### 1. 提交简单作业

提交一个打印 "Hello World" 的简单作业：

```bash
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "account": "my_project",
      "environment": {},
      "current_working_directory": "/tmp",
      "standard_output": "hello.out",
      "standard_error": "hello.err",
      "ntasks_per_node": 1,
      "cpus_per_task": 1,
      "memory_per_node": "1G",
      "name": "hello_world",
      "time_limit": "5",
      "partition": "default",
      "exclusive": false
    },
    "script": "#!/bin/bash\necho \"Hello World\"\ndate\n"
  }'
```

**响应：**
```json
{
  "job_id": "1"
}
```

### 2. 提交计算密集型作业

提交一个需要多个 CPU 核心的计算作业：

```bash
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "account": "compute_project",
      "environment": {
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8"
      },
      "current_working_directory": "/data/simulations/run001",
      "standard_output": "simulation.out",
      "standard_error": "simulation.err",
      "ntasks_per_node": 1,
      "cpus_per_task": 8,
      "memory_per_node": "32G",
      "name": "molecular_dynamics",
      "time_limit": "120",
      "partition": "compute-high-mem",
      "exclusive": false
    },
    "script": "#!/bin/bash\nset -e\necho \"Starting simulation at $(date)\"\n./run_simulation --input config.json --output results.dat\necho \"Simulation completed at $(date)\"\n"
  }'
```

### 3. 查询作业状态

```bash
# 查询作业 ID 为 1 的作业
curl http://localhost:8000/jobs/query/1
```

### 4. 取消正在运行的作业

```bash
curl -X POST http://localhost:8000/jobs/cancel/1
```

## Python 客户端

### 完整的 Python 客户端示例

```python
#!/usr/bin/env python3
"""
SCNS-Conductor Python 客户端示例
"""
import requests
import time
import json
from typing import Dict, Optional


class SCNSConductorClient:
    """SCNS-Conductor API 客户端"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
    
    def submit_job(
        self,
        script: str,
        name: str,
        account: str,
        work_dir: str,
        cpus: int = 1,
        time_limit: str = "60",
        environment: Optional[Dict[str, str]] = None,
        partition: str = "default"
    ) -> int:
        """
        提交作业
        
        Args:
            script: 作业脚本内容
            name: 作业名称
            account: 账户名称
            work_dir: 工作目录
            cpus: CPU 核心数
            time_limit: 时间限制（分钟）
            environment: 环境变量字典
            partition: 分区名称
        
        Returns:
            作业 ID
        """
        payload = {
            "job": {
                "account": account,
                "environment": environment or {},
                "current_working_directory": work_dir,
                "standard_output": f"{name}.out",
                "standard_error": f"{name}.err",
                "ntasks_per_node": 1,
                "cpus_per_task": cpus,
                "memory_per_node": f"{cpus * 2}G",
                "name": name,
                "time_limit": time_limit,
                "partition": partition,
                "exclusive": False
            },
            "script": script
        }
        
        response = requests.post(
            f"{self.base_url}/jobs/submit",
            json=payload
        )
        response.raise_for_status()
        
        job_id = int(response.json()["job_id"])
        print(f"✓ 作业已提交: ID={job_id}")
        return job_id
    
    def query_job(self, job_id: int) -> Dict:
        """
        查询作业状态
        
        Args:
            job_id: 作业 ID
        
        Returns:
            作业信息字典
        """
        response = requests.get(f"{self.base_url}/jobs/query/{job_id}")
        response.raise_for_status()
        return response.json()
    
    def cancel_job(self, job_id: int) -> None:
        """
        取消作业
        
        Args:
            job_id: 作业 ID
        """
        response = requests.post(f"{self.base_url}/jobs/cancel/{job_id}")
        response.raise_for_status()
        print(f"✓ 作业 {job_id} 已取消")
    
    def wait_for_job(
        self,
        job_id: int,
        check_interval: int = 5,
        timeout: Optional[int] = None
    ) -> str:
        """
        等待作业完成
        
        Args:
            job_id: 作业 ID
            check_interval: 检查间隔（秒）
            timeout: 超时时间（秒）
        
        Returns:
            最终状态
        """
        start_time = time.time()
        
        while True:
            job_info = self.query_job(job_id)
            state = job_info["state"]
            
            print(f"作业 {job_id} 状态: {state}")
            
            if state in ["COMPLETED", "FAILED", "CANCELLED"]:
                return state
            
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(f"作业 {job_id} 等待超时")
            
            time.sleep(check_interval)
    
    def get_job_output(self, job_id: int) -> tuple[str, str]:
        """
        获取作业输出
        
        Args:
            job_id: 作业 ID
        
        Returns:
            (stdout, stderr) 元组
        """
        job_info = self.query_job(job_id)
        job_log = job_info["job_log"]
        return job_log["stdout"], job_log["stderr"]


# 使用示例
if __name__ == "__main__":
    # 创建客户端
    client = SCNSConductorClient("http://localhost:8000")
    
    # 示例 1: 提交简单作业
    script = """#!/bin/bash
echo "Starting job at $(date)"
sleep 10
echo "Job completed at $(date)"
"""
    
    job_id = client.submit_job(
        script=script,
        name="test_job",
        account="my_project",
        work_dir="/tmp",
        cpus=2,
        time_limit="5"
    )
    
    # 等待作业完成
    final_state = client.wait_for_job(job_id)
    print(f"作业最终状态: {final_state}")
    
    # 获取输出
    stdout, stderr = client.get_job_output(job_id)
    print(f"\n标准输出:\n{stdout}")
    if stderr:
        print(f"\n标准错误:\n{stderr}")
```

## 常见场景

### 场景 1: 批量提交作业

```python
#!/usr/bin/env python3
"""批量提交多个作业"""
from scns_client import SCNSConductorClient

client = SCNSConductorClient()

# 要处理的数据文件列表
data_files = ["data001.csv", "data002.csv", "data003.csv"]

job_ids = []

for data_file in data_files:
    script = f"""#!/bin/bash
echo "Processing {data_file}"
python process.py --input {data_file} --output {data_file}.result
echo "Done"
"""
    
    job_id = client.submit_job(
        script=script,
        name=f"process_{data_file}",
        account="batch_project",
        work_dir="/data/processing",
        cpus=4,
        time_limit="30"
    )
    
    job_ids.append(job_id)
    print(f"已提交作业 {job_id} 处理 {data_file}")

print(f"\n共提交 {len(job_ids)} 个作业")
```

### 场景 2: 监控作业进度

```python
#!/usr/bin/env python3
"""监控多个作业的执行进度"""
from scns_client import SCNSConductorClient
import time

client = SCNSConductorClient()

job_ids = [1, 2, 3, 4, 5]  # 你的作业 ID 列表

while True:
    status_summary = {
        "PENDING": 0,
        "RUNNING": 0,
        "COMPLETED": 0,
        "FAILED": 0,
        "CANCELLED": 0
    }
    
    for job_id in job_ids:
        try:
            job_info = client.query_job(job_id)
            state = job_info["state"]
            status_summary[state] += 1
        except Exception as e:
            print(f"查询作业 {job_id} 失败: {e}")
    
    print(f"\n作业状态统计 ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    for state, count in status_summary.items():
        print(f"  {state}: {count}")
    
    # 检查是否所有作业都完成
    if status_summary["PENDING"] == 0 and status_summary["RUNNING"] == 0:
        print("\n所有作业已完成！")
        break
    
    time.sleep(10)  # 每 10 秒检查一次
```

### 场景 3: 参数扫描作业

```python
#!/usr/bin/env python3
"""参数扫描：提交不同参数组合的作业"""
from scns_client import SCNSConductorClient
import itertools

client = SCNSConductorClient()

# 参数网格
learning_rates = [0.001, 0.01, 0.1]
batch_sizes = [32, 64, 128]

for lr, bs in itertools.product(learning_rates, batch_sizes):
    script = f"""#!/bin/bash
python train_model.py \\
    --learning-rate {lr} \\
    --batch-size {bs} \\
    --epochs 100 \\
    --output model_lr{lr}_bs{bs}.pt
"""
    
    job_id = client.submit_job(
        script=script,
        name=f"train_lr{lr}_bs{bs}",
        account="ml_project",
        work_dir="/models/experiments",
        cpus=8,
        time_limit="180",
        environment={
            "CUDA_VISIBLE_DEVICES": "0",
            "OMP_NUM_THREADS": "8"
        }
    )
    
    print(f"提交训练作业: lr={lr}, bs={bs}, job_id={job_id}")
```

### 场景 4: 依赖作业链

```python
#!/usr/bin/env python3
"""提交有依赖关系的作业链"""
from scns_client import SCNSConductorClient

client = SCNSConductorClient()

# 第一步：数据预处理
preprocess_script = """#!/bin/bash
echo "Preprocessing data..."
python preprocess.py --input raw_data.csv --output processed_data.csv
"""

job1 = client.submit_job(
    script=preprocess_script,
    name="data_preprocess",
    account="pipeline",
    work_dir="/data/pipeline",
    cpus=2
)

print(f"提交预处理作业: {job1}")

# 等待第一步完成
state = client.wait_for_job(job1)
if state != "COMPLETED":
    print(f"预处理失败: {state}")
    exit(1)

# 第二步：模型训练
train_script = """#!/bin/bash
echo "Training model..."
python train.py --data processed_data.csv --model model.pkl
"""

job2 = client.submit_job(
    script=train_script,
    name="model_train",
    account="pipeline",
    work_dir="/data/pipeline",
    cpus=8
)

print(f"提交训练作业: {job2}")

# 等待第二步完成
state = client.wait_for_job(job2)
print(f"训练作业完成: {state}")
```

## 错误处理

### 处理常见错误

```python
#!/usr/bin/env python3
"""错误处理示例"""
from scns_client import SCNSConductorClient
import requests

client = SCNSConductorClient()

try:
    # 提交作业
    job_id = client.submit_job(
        script="#!/bin/bash\necho 'test'\n",
        name="test",
        account="test_account",
        work_dir="/tmp",
        cpus=1
    )
    
    # 查询作业
    job_info = client.query_job(job_id)
    
except requests.HTTPError as e:
    if e.response.status_code == 404:
        print("错误：作业不存在")
    elif e.response.status_code == 400:
        print(f"错误：请求参数无效 - {e.response.json()}")
    elif e.response.status_code == 500:
        print("错误：服务器内部错误")
    else:
        print(f"HTTP 错误: {e}")

except requests.ConnectionError:
    print("错误：无法连接到 API 服务")

except TimeoutError as e:
    print(f"错误：{e}")

except Exception as e:
    print(f"未知错误: {e}")
```

### 重试机制

```python
#!/usr/bin/env python3
"""带重试的作业提交"""
import time
from scns_client import SCNSConductorClient

def submit_with_retry(client, script, max_retries=3, **kwargs):
    """带重试的作业提交"""
    for attempt in range(max_retries):
        try:
            return client.submit_job(script=script, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避
                print(f"提交失败，{wait_time}秒后重试... ({e})")
                time.sleep(wait_time)
            else:
                raise

# 使用
client = SCNSConductorClient()
job_id = submit_with_retry(
    client,
    script="#!/bin/bash\necho 'test'\n",
    name="test",
    account="test",
    work_dir="/tmp",
    cpus=1
)
```

## 高级用法

### 实时查看作业日志

```python
#!/usr/bin/env python3
"""实时查看作业输出"""
from scns_client import SCNSConductorClient
import time

client = SCNSConductorClient()
job_id = 1  # 你的作业 ID

last_stdout = ""
last_stderr = ""

while True:
    job_info = client.query_job(job_id)
    state = job_info["state"]
    
    stdout = job_info["job_log"]["stdout"]
    stderr = job_info["job_log"]["stderr"]
    
    # 打印新增的输出
    if stdout != last_stdout:
        new_output = stdout[len(last_stdout):]
        print(new_output, end='')
        last_stdout = stdout
    
    if stderr != last_stderr:
        new_errors = stderr[len(last_stderr):]
        print(f"[STDERR] {new_errors}", end='')
        last_stderr = stderr
    
    # 作业完成时退出
    if state in ["COMPLETED", "FAILED", "CANCELLED"]:
        print(f"\n作业 {job_id} 结束，状态: {state}")
        break
    
    time.sleep(2)
```

---

**更多示例请参考项目文档或提交 Issue**

