return {
    owner_name = "",
    owner_character_id = 0,
    attack_skill_id = 0,
    attack_mode = "melee", -- melee|ranged|skill
    attack_range = 110, -- 远程基础射程（弓/弩），远程箭加成另计
    min_range = 60, -- 过近后撤阈值
    ranged_skill_id = 3000002, -- 远程箭（弓箭手 1 转，8 级共 +120）
    ranged_skill_bonus_per_level = 15, -- 远程箭每级射程增量
    ranged_skill_level = 0, -- 技能观察不可读时的兜底档位
    skill_mp_cost = 10,
    ammo_item_id = 2060000, -- 远程弹药（弓矢）
    ammo_low = 50, -- 低弹药阈值，低于时发布 combat/ammo_low
    hp_item = 0,
    mp_item = 0,
    follow_distance = 80,
    stop_distance = 40,
    pot_hp = 60,
    pot_mp = 30,
    loot_radius = 150,
}
