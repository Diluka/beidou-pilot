-- @tick.gear 3
-- @tick.budget_ms 100
-- @tick.overrun abort
-- @option[type=number,opt,default=120,min=3,max=1800] budget_seconds 任务总预算秒数（与客户端会话期限分开）
-- @option[type=int,opt,default=12,min=1,max=60] arrive_tolerance 到达水平容差（地图像素）
-- @option[type=number,opt,default=0.25,min=0,max=1] min_hp_ratio HP 低于此比例且无法用药时失败
-- @option[type=number,opt,default=0.7,min=0,max=1] heal_hp_ratio HP 低于此比例尝试用药
-- @option[type=int,opt,default=2000002,min=1] hp_item_id 普通恢复品 ID
-- @option[type=string,opt,default=auto,choices=auto|tank|clear|ignore] block_policy 挡路怪策略（M1/M2 未启用）
-- @option[type=int,opt,default=8,min=1,max=100] clear_limit 单次清怪上限（M1/M2 未启用）
-- @option[type=int,opt,default=8,min=0,max=100] max_replans 单图重规划上限

-- tick 跨图旅行入口（#176 M1/M2：单图可达路径 + 安全层骨架）。
--
-- 目录脚本包入口：由 CLI `travel` 查询跨图路线后注入 context.route/context.goal。
-- 用法示例：beidou-pilot travel shared/scripts/tick/travel --target-map 102020100
--           --target-x 225 --target-y 1755 --seconds 180
-- 每 tick 固定顺序 safety → combat → locomotion → travel_core；层返回 "halt" 表示
-- 本 tick 已接管（后续层不执行），"done" 表示会话完成。成功结束时 stop 后返回
-- "done"；不可恢复失败统一以 error("travel_failed ...") 结束会话。
local safety = require("safety")
local combat = require("combat")
local locomotion = require("locomotion")
local travel_core = require("travel_core")

local function finish(context)
    context.game.player.stop()
    return "done"
end

local function exit_failed(context)
    context.game.player.stop()
    local text = travel_core.failure_text(context)
    context.game.log(text)
    error(text)
end

local function main(context)
    local state = context.state
    if state.first_tick == nil then state.first_tick = context.tick.time end
    local character = context.game.character
    if type(character) ~= "table" then return nil end

    state.stage = "safety"
    local result = safety.step(context)
    if result == "failed" then return exit_failed(context) end
    if result == "done" then return finish(context) end
    if result == "halt" then return nil end

    state.stage = "combat"
    result = combat.step(context)
    if result == "failed" then return exit_failed(context) end
    if result == "done" then return finish(context) end
    if result == "halt" then return nil end

    state.stage = "locomotion"
    result = locomotion.step(context)
    if result == "failed" then return exit_failed(context) end
    if result == "done" then return finish(context) end
    if result == "halt" then return nil end

    state.stage = "travel_core"
    result = travel_core.step(context)
    if result == "failed" then return exit_failed(context) end
    if result == "done" then return finish(context) end
    return nil
end
