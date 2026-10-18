# HECATE Connect —— 鼠标(接收器) HID 私有协议静态分析报告

> 目标：`HECATE_Connect_installer.exe`
> 副本 SHA256：`A0C6A49744E5CCEEA3EC89EF2DDF07406769925E833DD563FD451548395F9097`
> 32 位 x86 MSVC PE（imagebase 0x00400000），未加壳。
> 分析方式：自写 PE 解析 + capstone 全 .text 线性反汇编（748,371 条指令）+ 交叉引用索引；
> 反汇编全文：`work/disasm.txt`，索引：`work/index.pkl`，关键函数反汇编：`work/decomp/`。
> 时间：2026-10-19

---

## 0. 结论速览（给实现者）

**电量查询（静态结论，已被动态被动抓包交叉验证）**

- 通道：`HID\VID_320F&PID_706E&MI_01&COL04`（UsagePage 0xFF1C / Usage 0x92，In=64 / Out=64），
  用 `CreateFileW` 打开后 **WriteFile 64 字节 output report**，再 **ReadFile 64 字节 input report**。
- 请求帧（64 字节，报告 ID 0x04 在第一个字节）：

```
偏移  值      含义
 0    04      报告 ID
 1    20      校验和低字节 = sum(bytes[3..63]) & 0xFF
 2    00      校验和高字节 = (sum(bytes[3..63]) >> 8) & 0xFF
 3    1A      命令码 CMD_STATUS_QUERY（读状态块）
 4    06      请求返回的字节数 = 6
 5    00      偏移/地址低字节
 6    00      偏移/地址高字节
 7    00      reserve
 8..63 00     全 0 填充（共 56 字节）
```

即：`04 20 00 1A 06 00 00 00` + 56 × `00`

- 响应帧（64 字节 input report）：
```
 0    04          报告 ID（与请求一致）
 1..7            设备原样回显请求的 [1..7]（实测校验和字节被回显而不是重算）
 7    00          正常；0xFF / 0xFE 为错误码（见 §5）
 8    5A          电量百分比 0..100（实测 0x5A=90 与界面 90% 一致）
 9    0/1/2       充电状态：0=正常/放电，1=充电中(powering)，2=已充满(powered)  ← 置信度中高
 10..13          其余状态块字节（App 未使用；14 以后为 0）
```

- **协议不做 CRC/校验和验证**（实测发全 0 校验和也能正常回包；App 自己也不校验回包），
  但建议仍按本报告算法填 [1][2] 以保持一致。
- 轮询：App 约每 3 秒查询一次（用户侧观测），软件用异步（overlapped）读，等 1000ms / 5000ms 超时，失败重试 1 次。
- 另有握手帧 `04 AA 00 AA 00 00 00 00`（CMD 0xAA，无 payload），响应 [8]=0xFF 表示设备就绪；
  App 连接后会以 50ms 间隔最多重试 25 次握手。
  **CMD 0xAA 的语义已确认 = “获取 2.4G 模式”**：失败分支的调试字符串是
  `L"获取2.4G模式失败"`（rva 0x29233c，`OutputDebugStringW` @0x460e85），成功分支打印 `L"获取2"`（rva 0x292354）；
  同一处日志把 transport 的 `+0x64c` 标志（= 高层对象 `+0xec8`）切到 2.4G 模式（`0x47eb40(transport,2)`），
  所以 `+0xec8` 是 **2.4G 无线模式标志**，不是充电位（它只控制 UI 里“无线 logo”是否显示）。

### 0.1 状态块 6 字节（resp[8..13]）语义

| 报告偏移 | 状态块下标 | App 里的用途 | 语义 | 置信度 |
|---|---|---|---|---|
| 8 | data[0] | `Format("%d%s", data[0], "%")` + `SetValue(100-data[0])` | **电量百分比 0..100** | 高（实测 0x5A=90） |
| 9 | data[1] | switch → `power.png` / `powering.png` / `powered.png` | **充电状态 0=放电 1=充电中 2=已充满** | 中高 |
| 10 | data[2] | 无人读取 | 未知 | — |
| 11 | data[3] | 被 App 用“2.4G 模式标志”覆盖后才用于 UI | 设备值未知（App 不消费） | — |
| 12 | data[4] | `SendMessageW(hwnd, 0xD01, data[4], 0)`（0x48aad2 / 0x49530d） | 未知（转发给主窗口的自定义消息，疑为托盘/第二 UI 用的状态位） | 低 |
| 13 | data[5] | 仅 UI 变体 `[this+0x880]==3` 时：1→iPhone、2→Samsung 图标 | 无线充电“手机类型” | 中 |

也就是说：**做成品只需要 resp[8]（电量）和 resp[9]（充电状态）**，后 4 字节 App 自己也没用全。

---

## 1. 传输层（HID 封装类）

C++ 类（无 RTTI 名，按用途称 `CHidDevice`，sizeof≈0x2D0）：

| 函数地址 | 作用 | 证据 |
|---|---|---|
| `0x4bffb0` | 构造：保存路径 + 打开参数（access/share/flags），调用 open | 0x4bffe0 循环拷贝宽字符串到 `this+0x20` |
| `0x4bfef0` | `Open()`：构造 `CreateFileW` 参数并调用 | `call [0x644b74]=CreateFileW` @0x4bff70 |
| `0x4bf480` | 打开成功后：`HidD_GetPreparsedData` / `HidD_GetAttributes` / `HidP_GetCaps`，建立 button/value caps 映射 | call @0x4bf4a6/0x4bf4be/0x4bf4d5 |
| `0x4c0060` | `ReadInputReport(buf,len,overlapped)` → `ReadFile` | `call [0x644b40]=ReadFile` @0x4c00b2 |
| `0x4c0120` | `WriteOutputReport(buf,len,overlapped)` → `WriteFile` | `call [0x644b70]=WriteFile` @0x4c0172 |
| `0x4c0020` | `Close()`（CloseHandle + 释放） | |
| `0x4bf280` | 静态枚举：`HidD_GetHidGuid`+`SetupDiGetClassDevsW`+`EnumDeviceInterfaces`+`GetDeviceInterfaceDetailW`，返回所有 HID 设备路径 `vector<wstring>` | call @0x4bf2aa/0x4bf2c6/0x4bf32c/0x4bf349 |

设备句柄字段：`this+0x1c`=HANDLE；`this+0x20`=内联的 device interface path（宽字符）。
`CreateFileW` 参数（0x4bff35..0x4bff70）：
- `dwDesiredAccess = (read? 0x80000000 : 0) | (write? 0x40000000 : 0)`
- `dwShareMode = 3`（FILE_SHARE_READ|WRITE）——所以**可以和其他程序同时打开**（与“普通权限可读”一致）
- `dwCreationDisposition = 3`（OPEN_EXISTING）
- `dwFlagsAndAttributes = 0x40000000`（FILE_FLAG_OVERLAPPED，异步）

设备路径筛选：解析 path 里的 `vid_` / `pid_` / `&mi_` / `&col` 十六进制值（`StrStrIW`+`wcstoul`），
函数：`0x450f80`(vid) `0x450fd0`(pid) `0x451020`(mi) `0x451070`(col)，
调用者 `0x45e0d9`（构建设备对象并把 4 个值存到对象 +0xac/+0xaa/+0xa6/+0xa4）。

**集合/接口 → HID collection 映射表**（静态初始化，位于 .data：0x6e3c30 起，步长 0x9C）：
每项 `{u16 vid; u16 pid; u16 mi; u16 col; u16 ?; u16 ?; u16 usagePage; u16 usage; u16 ?; u16 id; ... CDuiString name}`。
对 `320F:706E` 明确登记了两项（初始化代码 0x404009 起）：

```
vid=320F pid=706E mi=1 col=4  usagePage=FF1C usage=0092   ← 厂商私有集合（本协议用这个）
vid=320F pid=706E mi=1 col=3  usagePage=000C usage=0001   ← Consumer Control（多媒体键）
```
同一张表里 `320F:706B` 也登记了 col4(FF1C/92) 与 col3(000C/01)，说明这是“已知 HID 集合表”，
用于从枚举到的 path 中挑出厂商集合。**这是“走 MI_01&COL04”的静态依据**（置信度高）。

---

## 2. 请求/响应帧格式（核心）

### 2.1 帧构造（16 个命令函数共用模板）

命令函数列表（全部以 `ecx = transport 对象`，调用统一的 `0x47b430` 发送）：

| 地址 | 命令码 [3] | 参数/说明 |
|---|---|---|
| `0x47c140` | `0x01` | 无 payload（校验和=0x0001） |
| `0x47c350` | `0x02` | 1 个 int 参数 |
| `0x47c570` | `0x1C` | 无 payload |
| `0x47c780` | `0x03` | 读设备信息（回填 ~34 字节：8×movsd+movsw） |
| `0x47ca60` | `0x09` | 2 参数 |
| `0x47cd20` | `0x15` | 2 参数 |
| `0x47cfb0` | `0x28` | 2 参数 |
| `0x47d240` | `0x29` | 2 参数 |
| `0x47d4d0` | `0x17` | 2 参数 |
| `0x47d710` | `0x07` | 通用读存储块：`[4]=len, [5]=offset&0xFF, [6]=offset>>8`，回填到调用者缓冲 |
| `0x47d9b0` | `0x1B` | 1 参数 |
| `0x47dc60` | `0x0B` | 4 参数 |
| **`0x47e6c0`** | **`0x1A`** | **读 6 字节状态块（电量）——本报告核心** |
| `0x47e1b0` | `0x06` | 3 参数 |
| `0x47e430` | `0x05` | 3 参数 |
| `0x47e8b0` | `0xAA` | 无 payload，返回 bool（握手/就绪） |

通用构造（以 `0x47e6c0` cmd 0x1A 为例，见 `work/decomp/cmd1a_47e6c0.txt`）：

```
memset(buf,0,0x40)                     ; 0x47e6d9..0x47e6ea
buf[0] = 0x04                          ; 0x47e6ed..0x47e6f5   ← 报告 ID
buf[3] = 0x1A                          ; 0x47e6fa..0x47e702   ← 命令码
buf[4] = (u8)arg1                      ; 0x47e730..0x47e73b   ← 请求长度
buf[5] = (u8)arg2                      ; 0x47e73f..0x47e74a   ← offset 低
buf[6] = (u8)(arg2 >> 8)               ; 0x47e74e..0x47e75c   ← offset 高
buf[7] = 0
sum = 0; for (i = 3; i < 0x40; i++) sum += buf[i];   ; 0x47e760..0x47e7a5
buf[1] = sum & 0xFF                    ; 0x47e7a7..0x47e7b5   ← 校验和低
buf[2] = (sum >> 8) & 0xFF             ; 0x47e7b9..0x47e7c9   ← 校验和高
call 0x47b430(transport, buf, 0x40, resp, 0x40, &outLen)
```

**没有第 63 字节校验和**（用户动态测试的猜想不成立）：第 63 字节始终是 0 填充；
校验和是 **16 位字节和，放在 [1][2]，覆盖 [3..63]**。已用两条实测帧验证：
- `04 20 00 1A 06 00 00 00 5A…`：sum([3..63]) 请求端 = 0x1A+0x06 = 0x20 → [1]=0x20,[2]=0x00 ✓
- `04 AA 00 AA 00 00 00 00 FF…`：sum = 0xAA → [1]=0xAA,[2]=0x00 ✓

校验算法（伪代码）：
```c
uint16_t sum = 0;
for (int i = 3; i < 64; i++) sum += frame[i];
frame[1] = sum & 0xff; frame[2] = sum >> 8;
```

### 2.2 收发（transact）

`0x47b430` = “发一帧 + 收一帧”的封装：内部 `0x4c0120`(WriteFile) → `0x4c0060`(ReadFile)，
带 overlapped 事件与超时；`0x47bf10` 是同一逻辑的另一份实现（超时 1000/5000ms 两档），
**收到响应后校验 `resp[3] == req[3]`（命令码回显），不匹配则重读，最多重试 1 次**：

```
0x47c0a5: ecx = req[3]; eax = resp[3]; cmp; jne -> 重试/失败
```
响应也必须是 64 字节 input report（同一个 HID 句柄、同一个 collection 上读回，
设备把请求的 [0..7] 回显、数据放在 [8..]）。

### 2.3 响应状态字节

所有命令函数在收到回包后统一检查 `resp[7]`：

```
resp[7] == 0xFF  -> 返回 -102 (0xFFFFFF9A)
resp[7] == 0xFE  -> 返回 -103 (0xFFFFFF99)
否则成功，payload 从 resp[8] 起
```
（实测正常回包 [7]=0x00，与“回显请求 [7]=0”吻合；错误时设备会改写该字节。）

---

## 3. 电量命令（CMD 0x1A）完整证据链

### 3.1 调用者

`0x47e6c0` 的调用者只有两处，都是“刷新设备电量 UI”：

1. `0x48aa00`（类方法，`this` 为高层设备对象；`this+0x87c` 是 transport 对象，`this+0x1570` 是 UI 对象）
2. `0x495210`（另一个设备类的同类方法，查询前多一次 Cmd 0xAA 握手）

`0x48aa00` 逻辑（`work/decomp/powerupdate_48aa00.txt`）：

```
if (this->connected == 0) return;                       ; +0x890
uint8_t buf[6] = {0};
ret = Cmd1A(transport, buf, 6, 0);                      ; 0x47e6c0(dst, len=6, offset=0)
if (ret != 1) return;
buf[3] = (this->wirelessMode != 0) ? 1 : 0;             ; +0xec8，UI 里控制“无线图标”
PowerUI_Update(this->ui, buf, 6);                       ; 0x4353c0  ← 见 3.2
this->SendMessage(WM_USER+0xD01, buf[1]?) // 通知托盘
```

（`0x495210` 相同，只是开始处先 `CmdAA()` 握手、失败则直接返回。）

### 3.2 UI 解析（0x4353c0，CMpDevicePowerUI::Update）

输入：`data[6]`。关键指令（`work/decomp/powerui_4353c0.txt`）：

```
0x435639  progress.SetValue(100 - data[0]);   ; data[0]=电量百分比（Progress 条显示 100-x）
0x435660  Format(L"%d%s", data[0], L"%")      ; 文本显示 "90%"
0x4356b4  if (data[3] != 0) 显示无线图标        ; 由调用者写入，来自 mode 标志，不是设备返回值
0x435723  switch (data[1]) {
             0: SetBkImage(device_power_status, L"file='power/power.png'");     // 普通电池
             1: SetBkImage(device_power_status, L"file='power/powering.png'");  // 充电中
             2: SetBkImage(device_power_status, L"file='power/powered.png'");   // 已充满
          }
0x43586d  if (data[5] == 1) "Phone_type_iphone"; == 2: "Phone_type_samsung"  // 仅充电板机型
```

所以：
- **偏移 8（data[0]）= 电量百分比**，直接 0..100，**没有任何换算/缩放/clamp 代码**（不是 0..255 映射）。
- **偏移 9（data[1]）= 充电状态枚举 0/1/2**（普通/充电中/已充满）——置信度中高（由图标选择逻辑推定）。
- 偏移 8 之后只用到 data[1]、data[5]；data[3] 被 App 覆盖，**设备返回值中的第 4 个字节没被使用**。

### 3.3 命令 0xAA（握手）

`0x47e8b0`（`work/decomp/cmdaa_47e8b0.txt`）：
帧 = `04 <sum=AA> 00 AA 00 00 00 00` + 56×00；
返回 `bool ok = (发送成功 && resp[7]==0 && resp[8]==0xFF)`。

调用点：
- `0x460e57`：设备接入后的等待循环——`CmdAA` 失败则 `Sleep(50ms)` 重试，最多 25 次
  （成功/超时后 `OutputDebugString` 打印调试串），说明它是**“设备就绪”握手/唤醒**。
- `0x495283`：刷新电量前先握手，失败就不读电量。
- 实测 `04 AA …` 回包 offset8 = 0xFF = 就绪。

---

## 4. 给 C# 实现的最小协议

```csharp
// 1) 打开 HID\VID_320F&PID_706E&MI_01&COL04  (FileShare.ReadWrite, 不需要管理员)
// 2) 组帧
byte[] req = new byte[64];
req[0] = 0x04;          // report ID
req[3] = 0x1A;          // CMD_STATUS
req[4] = 0x06;          // 要 6 字节
ushort sum = 0;
for (int i = 3; i < 64; i++) sum += req[i];
req[1] = (byte)(sum & 0xFF);
req[2] = (byte)(sum >> 8);
// 3) WriteFile(handle, req, 64, ...)   // 有的 HID 栈要求长度 = OutputReportByteLength = 64
// 4) ReadFile(handle, resp, 64, ...)   // 阻塞或 OVERLAPPED，超时 ~1s
// resp[3] 必须 == 0x1A，resp[7] 必须 == 0
int batteryPercent  = resp[8];          // 0..100
int chargeState     = resp[9];         // 0=放电 1=充电中 2=已充满（待实测确认 1/2 顺序）
```

可选握手（App 行为，非必需；若设备不应答 0x1A 可先发一次）：
`04 AA 00 AA 00 00 00 00` + 56×00 → 期待 `resp[8]==0xFF`。

---

## 5. 置信度与不确定之处（诚实标注）

| 结论 | 置信度 | 依据 |
|---|---|---|
| 通道 = MI_01&COL04（FF1C/92）64B output→input | **高** | 设备描述符 + 静态集合表登记 320F/706E 的 col4(FF1C/92) + 代码只用 WriteFile/ReadFile 64B |
| 帧 = 报告ID 0x04 + 16bit 校验和[1..2] + cmd[3] + len[4] + off[5..6] | **高** | 反编译构造模板 + 实测帧完全吻合（校验和数值逐一对应） |
| 电量 = resp[8]，0..100 整数直出 | **高** | 反编译 UI 解析 + 实测 0x5A=90 与界面一致 |
| cmd 0x1A / len=6 / offset=0 是“读状态块” | **高** | 6 个命令构造函数同一模板；len 字段同一参数也用于 memcpy 长度 |
| resp[7] 是状态字节（0xFF/-102、0xFE/-103） | 中高 | 16 个命令函数统一检查该字节；正常回包为 0（回显） |
| resp[9] = 充电状态 0/1/2 | **中高** | 由 UI 图标选择逻辑推定（power/powering/powered），需要实机插线对比 offset9 |
| resp[10..13] 语义 | 低 | App 只把 data[4] 转发给自定义消息 0xD01、data[5] 当手机类型；其余不消费 |
| 0xAA = "获取 2.4G 模式"握手 | 高 | 调试字符串 `获取2.4G模式失败` + 成功分支切 2.4G 模式 + 50ms×25 重试 |
| 是否真的忽略校验和 | 中高 | 用户实测全 0 校验和可回包；静态上看不出设备端逻辑 |
| Progress 条为何用 100-x | 低（未解释） | `SetValue(100 - data[0])`，与文本 "x%" 不一致，可能是 UI 设计/遗留 bug，不影响取值 |

**未解/未做**
- 没有找到“寄存器映射表”（battery/capacity/charge 的地址）。静态证据表明 0x1A 返回的 6 字节是**固定状态块**，
  不会按地址读；cmd 0x07 才是带 `len/offset` 的通用存储块读（可能用于固件/配置），未找到其地址空间含义。
- 6 字节块里 [2][3][4][5] 的具体语义未完全确定（App 只用 [0][1]；[3] 被覆盖成 2.4G 标志，[4] 只被转发给窗口消息 0xD01，[5] 仅充电板 UI 变体当手机类型用）。
- 两个高层设备类分别调用 `0x48aa00`/`0x495210`，未 100% 确定哪个对应 G3M PRO 鼠标（一个可能是鼠标垫型号），
  但两者使用**完全相同的 Cmd 0x1A**，不影响协议结论。
- Ghidra 11.4.2 下载**已按 Lead 指示中止**（约 130MB 时取消，未解压）；全部结论来自 capstone 线性反汇编 + 交叉引用，已与动态抓包互证。

---

## 6. 关键地址速查

| 地址 | 说明 |
|---|---|
| 0x47b430 / 0x47bf10 | 发帧+收帧（transact），含 resp[3]==req[3] 校验、超时、重试 |
| 0x47c140 … 0x47e8b0 | 16 个命令构造函数（见 §2.1 表） |
| **0x47e6c0** | **CMD 0x1A 电量/状态块读取构造** |
| **0x48aa00 / 0x495210** | 电量刷新（调用 0x47e6c0，长度 6，offset 0） |
| **0x4353c0** | CMpDevicePowerUI::Update（解析 data[0]=%, data[1]=充电状态） |
| 0x4c0060 / 0x4c0120 | CHidDevice::ReadInputReport / WriteOutputReport（ReadFile/WriteFile） |
| 0x4bffb0 / 0x4bfef0 / 0x4bf480 | CHidDevice 构造 / Open(CreateFileW) / 打开后 caps 初始化 |
| 0x4bf280 | HID 设备枚举（SetupDi* + HidD_GetHidGuid） |
| 0x450f80/0x450fd0/0x451020/0x451070 | 从 path 解析 vid/pid/mi/col |
| 0x6e3c30 起（步长 0x9C） | 静态“已知 HID 集合”表（写入点 0x404009/0x404095） |
| 0x6dfef8 起（步长 0x230） | 型号表 {vid,pid,type, 4×CDuiString}，写入点 0x402480-0x402980 |
| 0x2905c0 / 0x2905e0 | 型号串 `HECATE_G3_M_PRO` / 产品串 `G3M PRO`（型号字符串表写入点 0x402fb0 起） |

## 7. 复核用文件

- `work/disasm.txt` —— 全 .text 反汇编（748k 行）
- `work/imports.txt` —— 导入表（含 IAT 地址）
- `work/strings.txt` —— ASCII/UTF-16 字符串（含 RVA）
- `work/decomp/*.txt` —— 本报告引用的所有函数反汇编
- `work/cmd/send_*.txt` —— 16 个命令构造函数原始反汇编
- `work/pe.py` / `work/q.py` / `work/build_index.py` —— 分析脚本（`python work/q.py func 0x47e6c0` 可复查）
