# adb-rescue

零接触 ADB：给**屏幕/触摸坏掉的安卓手机**建立 ADB 连接并完成授权。

No-touch ADB: connect to, and authorize, an Android device whose screen or digitiser is dead.

## 为什么

手机屏坏了 → `adb devices` 永远是 `unauthorized` → 那个「是否允许 USB 调试？」弹窗没人能点。
常规解法（OTG 键盘、换屏、fastboot）都需要人动手或拆机。

这里的做法是 **AOA（Android Open Accessory）HID 注入**：通过 USB 控制请求把手机当成配件，
注册一个 HID 键盘/鼠标，直接从主机"按"下那个允许按钮。全程不需要碰手机。

## 两个技能

| 技能 | 作用 | 何时用 |
|---|---|---|
| [`adb-connect/`](adb-connect/) | 连接层：USB 枚举、节点权限、无线 5555、状态码解码、断线保活 | adb 看不到设备 / `no permissions` / 开无线 / 重启后恢复 |
| [`adb-aoa-hid/`](adb-aoa-hid/) | 授权层：AOA 切换 + HID 键盘/鼠标注入 | `unauthorized`、弹窗点不了 |

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

## 三个关键坑

1. **`REGISTER_HID` 的参数**：`wValue=hid_id`、`wIndex=描述符长度`、`wLength=0`。
   把长度传成 `wLength` 会 100% STALL —— 哪怕设备报告 AOA protocol 2。
2. **`TAB` 然后 `ENTER`** 就能点中允许：EMUI 弹窗的「始终允许」复选框默认 `focused=true`。
3. **授权成功那一下 adbd 会重启**，设备短暂 `absent`。这 10–15 秒内 `adb kill-server`
   会把结果冲掉，之后永远卡在 `unauthorized`。

完整协议表、描述符十六进制、失败模式对照见各技能里的 `references/`。

## 适用性

- 已在 Huawei MAR-TL00（Android 10 / EMUI 10）实测通过，取得 `device` + root-less shell。
- 任何支持 AOA 2.0 的设备理论上都可用（`GET_PROTOCOL` 返回 ≥ 1），但不同厂商的
  HID 解析器实现差异很大，**不作为通用保证**。
- 不需要 root、不需要 OTG、不需要换屏、不需要 fastboot。

## 免责

仅用于**你自己拥有或已获授权**的设备。注入键盘事件等同于你亲手操作这台机器，
能做的不只是点"允许"。请自行判断后果。

MIT License.
