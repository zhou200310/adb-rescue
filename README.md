# adb-rescue

零接触 ADB：给**屏幕/触摸坏掉的安卓手机**建立 ADB 连接并完成授权。

No-touch ADB: connect to, and authorize, an Android device whose screen or digitiser is dead.

---

## 为什么

手机屏坏了 → `adb devices` 永远是 `unauthorized` → 那个「是否允许 USB 调试？」弹窗没人能点。
常规解法（OTG 键盘、换屏、fastboot）都需要人动手或拆机。

这里的做法是 **AOA（Android Open Accessory）HID 注入**：通过 USB 控制请求把手机当成配件，
注册一个 HID 键盘/鼠标，直接从主机"按"下那个允许按钮。全程不需要碰手机。

---

## 两个技能

| 技能 | 作用 | 何时用 |
|---|---|---|
| [`adb-connect/`](adb-connect/) | 连接层：USB 枚举、节点权限、无线 5555、状态码解码、断线保活 | adb 看不到设备 / `no permissions` / 开无线 / 重启后恢复 |
| [`adb-aoa-hid/`](adb-aoa-hid/) | 授权层：AOA 切换 + HID 键盘/鼠标注入 | `unauthorized`、弹窗点不了 |

---

## 快速开始

```bash
# 1. 看看有什么
bash adb-connect/scripts/adb_connect.sh status

# 2. 修节点权限（每次重枚举都要重跑）
bash adb-connect/scripts/adb_connect.sh perms

# 3. 进 accessory 模式
python3 adb-aoa-hid/scripts/aoa_hid.py --switch

# 4. 按「允许」——弹窗的“始终允许”复选框默认有焦点，TAB 到“确定”再回车
python3 adb-aoa-hid/scripts/aoa_hid.py --keys tab,enter

# 5. 没中就让脚本自己轮换重试
bash adb-aoa-hid/scripts/autohit.sh

# 6. 授权后开无线
bash adb-connect/scripts/adb_connect.sh wifi <phone-ip> 5555
```

---

## 三个关键坑

1. **`REGISTER_HID` 的参数**：`wValue=hid_id`、`wIndex=描述符长度`、`wLength=0`。
   把长度传成 `wLength` 会 100% STALL —— 哪怕设备报告 AOA protocol 2。
2. **`TAB` 然后 `ENTER`** 就能点中允许：EMUI 弹窗的「始终允许」复选框默认 `focused=true`。
3. **授权成功那一下 adbd 会重启**，设备短暂 `absent`。这 10–15 秒内 `adb kill-server`
   会把结果冲掉，之后永远卡在 `unauthorized`。

完整协议表、描述符十六进制、失败模式对照见各技能里的 `references/`。

---

## ⚠️ 注意事项（用之前请全部读完）

### 一、安全与合规

- **只能用于你自己拥有、或已获得明确授权的设备。**
  HID 注入等同于"你亲手在这台机器上敲键盘"——它能点的**不只是**那个允许按钮。
  锁屏、支付宝、微信，凡是不需要额外生物识别的操作，都能被这样点开。
- 如果设备不是你的，或者里面有别人的数据，**立刻停止**。
- 别在借来的、公司的、二手的未清机器上跑这套流程。
- 本仓库不含任何真实设备的序列号、IP、密钥；`--serial` 是占位参数，请自行传入。

### 二、不可逆的部分

- **一旦点了「始终允许」并勾选，这台主机的公钥就写进了设备的 `/data/misc/adb/adb_keys`，
  永久生效。** 拔线、重启、换系统版本都不会失效。
- 撤销只有两条路：设备上"撤销 USB 调试授权"（需要能操作屏幕），或 root 后删 `adb_keys`。
  **如果屏幕是坏的，等于撤销不了。**
- 所以：**别拿别人的机器试，也别在临时借用的电脑上跑**——那台电脑会永久获得该手机的控制权。

### 三、无线 adb 的暴露面

- `adb tcpip 5555` 之后，**同一局域网内任何主机**都能连上并触发授权弹窗。
- 有人点了"始终允许"，那台陌生机器就永久可信了。看到不认识的指纹先核对：
  `base64 -d adbkey.pub | md5sum`。
- 用它排查完，建议 `adb usb` 关掉 TCP 模式。
- Android 11+ 有配对码机制，**10 及以下没有**，5555 就是裸奔。

### 四、兼容性（别当成万能）

- 已在 **Huawei MAR-TL00 / Android 10 / EMUI 10** 实测通过，拿到 `device` + 免 root shell。
- 其他机型**不保证**。AOA 2.0 只是"协议支持"，不代表厂商内核的 HID 解析器能接受你的描述符；
  华为以外的机器上 `hid_add_device` 可能直接失败，而且失败日志只在手机端 dmesg 里，主机看不到。
- 有的 ROM 会砍掉 `f_accessory`；有的 OEM 在 accessory 模式下仍然强制要求确认。
- **失败时不要怀疑命令写错，先换一套更简单的 HID 描述符再试。**
- 部分机型（如小米）需要额外打开「USB 调试（安全设置）」才能注入点击。

### 五、操作层面的坑

- **AOA 切换会让设备 USB 断开重枚举**（`12d1:xxxx` → `18d1:2d01`），
  正在传输的数据、正在跑的 `adb install`、正在投的屏都会断。别在关键时刻做。
- **单 Type-C 口设备有物理互斥**：插键盘就进 host 模式，USB 数据断开；
  这套方案的好处正是**不需要插键盘**。
- **每次尝试要 20–30 秒**（切换 + 注册 + 注入 + 等 adbd 重启），做好跑十几轮的心理准备。
- **adb server 会独占 USB 接口**：做注入前必须 `adb kill-server`，并停掉任何自动重连的看门狗，
  否则 pyusb 写入必失败/STALL。
- **`/dev/bus/usb/*/*` 的权限每次重枚举都会重置**为 `root:root 0644`，
  `no permissions (not in plugdev group)` 说的就是这个，不是设备问题。
- **端点 halt 用 `clear_halt` 清**，断电重启清不掉。
- **脚本别放 `/tmp`**：会被清空。放工作目录。

### 六、数据与责任

- 这套流程只负责"把门打开"。之后你能 `pull` 整个 `/sdcard`、能 `pm uninstall`、能 `input tap`。
  做什么、删什么，责任在使用者。
- 建议在动手前先 `adb pull /sdcard` 做一份只读备份，再考虑任何写操作。
- 若设备处于加密状态且不知道锁屏密码，本方法**无法**解密数据——它只能点按钮，不能破加密。

---

## 故障速查

| 现象 | 真实原因 | 怎么办 |
|---|---|---|
| `adb devices` 一直是 `unauthorized` | 弹窗没被点中 | 换按键组合，或改用 `--click` 点坐标 |
| 出现过一次 `authorizing`，又退回 `unauthorized` | adb server 在握手中间被 kill | 让它跑完，10–15 秒内别动 |
| 每个控制请求都 STALL | `REGISTER_HID` 的 `wIndex`/`wLength` 传反，或 adb server 占着接口 | 先 `adb kill-server`，再核对参数 |
| 设备从总线上消失 | 切 AOA 时重枚举 | 等 5–20 秒，重新 `find()` |
| `no permissions (user ... not in plugdev group)` | USB 节点权限 | `adb_connect.sh perms` |
| 无线连上但 `offline` | 那个端口不是 adbd | 别浪费时间，换端口/换通道 |
| 重启后无线没了 | `adb tcpip` 不持久 | 插 USB（已授权，直接 `device`）→ 再 `tcpip 5555` |

---

## 怎么退出 / 恢复

- **退出 accessory 模式**：直接拔 USB 线，设备会自己回到正常模式。
- **关掉无线调试**：`adb usb`（会重启 adbd，回 USB 模式）。
- **撤销授权**：设备端「开发者选项 → 撤销 USB 调试授权」，或 root 后删 `/data/misc/adb/adb_keys`。

---

## 适用性

- 需要：Linux 主机、`pyusb`、`adb`、对 `/dev/bus/usb` 的写权限（特权容器或 udev 规则）。
- 不需要：root、OTG 转接头、换屏、fastboot、解锁 bootloader。
- 已知限制：厂商私有协议（华为 HDB 等）不在此方案覆盖范围内。

---

## 免责

本项目仅用于设备救援与合法的自有设备维护。作者不对因使用本工具造成的
数据丢失、设备损坏、授权泄露或法律问题承担责任。使用前请确认你对设备拥有处置权。

MIT License.
