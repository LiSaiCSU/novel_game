"""Create the second official short-drama genre wave.

The pack format deliberately stays declarative: every world gets its own
locations, people, knowledge boundary, tasks, clocks and authored opening.
Run once only for new pack directories; this command refuses to overwrite a
creator's content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1] / "content"


SPECS: list[dict[str, Any]] = [
    {
        "key": "seoul_blackout_v1", "slug": "seoul-blackout", "title": "零点首尔：校友会只剩一个生门",
        "genre": "korean_escape_thriller", "tags": ["韩式", "逃杀", "密室", "悬疑"],
        "theme": {"accent": "#c82635", "background": "#15171d", "surface": "#f4f0e9", "text": "#1c2028"},
        "world": "首尔·汉江会馆", "role": "被匿名邀请回国的前奖学金生", "age": 26,
        "hook": "慈善校友会刚把你评为‘最失败校友’，会馆的防火门便全部落锁。大屏列出九个人的名字：其中一人伪造了学历，午夜前交不出真正的录取档案，整层氧气会自动切断。",
        "fact": "会馆的逃生系统并非随机惩罚，而是在逼九位校友交出二十年前一份被篡改的奖学金名单。",
        "deadline": "午夜氧气切断", "humor": "笑点来自精英校友在求生时还要争谁的名片更高级，以及礼宾部一本正经地提醒大家损坏地毯要赔偿。",
        "locations": [
            ("reunion_hall", "汉江会馆校友厅", "香槟塔还没倒，九张椅子下的门锁却已亮红。"),
            ("service_corridor", "后勤走廊", "宴会厅的背景音乐在这里变成断断续续的警报。"),
            ("archive_lift", "封存档案电梯", "电梯只停在不存在的负一层。"),
            ("rooftop_garden", "玻璃屋顶花园", "能看到汉江夜景，也能看到唯一一架没有起飞的无人机。"),
            ("security_room", "安保监控室", "九块屏幕里有一块比现实快了三分钟。"),
            ("old_library", "旧校史馆", "落灰的毕业册被人撕走了其中两页。"),
            ("kitchen", "宴会后厨", "主厨把应急广播当成新的上菜口令。"),
            ("parking_floor", "地下停车层", "每辆车的车牌都贴着同一个校徽贴纸。"),
            ("dean_office", "名誉院长室", "墙上全是成功校友，唯独没有奖学金生。"),
            ("river_dock", "汉江临时码头", "一艘观光船在零点前不会靠岸。"),
            ("server_vault", "校友数据机房", "备用电源只够开一次门或发一次全员通知。"),
            ("chapel", "会馆礼拜堂", "告解室里留着一部仍在充电的旧手机。"),
            ("laundry_room", "制服洗衣房", "所有礼宾制服胸牌都被换成了数字。"),
            ("medical_bay", "会馆医务室", "氧气面罩数量刚好少一个。"),
            ("freight_exit", "货运卸货口", "门禁日志显示有人在宴会开始前带走了一箱纸质档案。"),
        ],
        "people": [
            ("姜允书", "前奖学金生、玩家旧友", "找回被取消的录取资格", "她手里的录取通知书日期比官方早一年"),
            ("韩泰勋", "财团继承人", "让所有人接受他的救援方案", "他知道氧气不会真正断，但不知道谁会先恐慌"),
            ("崔敏静", "电视台制片人", "拿到独家直播画面", "匿名邀请函由她的旧账号发出"),
            ("朴志浩", "安保工程师", "绕过楼层锁定", "他曾替校方删过一段监控"),
            ("李瑞妍", "检察官", "确认名单是否构成犯罪证据", "她母亲正是当年审核委员会成员"),
            ("吴道贤", "名誉院长助理", "保住会馆和院长名誉", "负一层档案柜的钥匙在他袖扣里"),
            ("金夏琳", "急诊医生", "确保无人因恐慌受伤", "她认识那名从名单上消失的学生"),
            ("郑宇成", "礼宾经理", "维持秩序", "他把每个人的房卡复制了一份"),
            ("宋恩雨", "实习礼宾", "拿回自己被扣下的工资", "她在洗衣房发现过带血的旧校徽"),
        ],
        "cover": "seoul-blackout-cover-v1.png",
        "cover_alt": "首尔高层校友会馆在午夜断电，九名成年校友围着亮红的长桌门锁，玻璃外是汉江夜景",
    },
    {
        "key": "zombie_station_v1", "slug": "last-train-terminal", "title": "最后一班地铁：感染者在终点站",
        "genre": "zombie_apocalypse", "tags": ["丧尸", "末日", "地铁", "生存"],
        "theme": {"accent": "#d85b2a", "background": "#111b1f", "surface": "#e8ece8", "text": "#172126"},
        "world": "临港市·地铁零号线", "role": "夜班调度员", "age": 29,
        "hook": "末班车进站时，你亲手按下封站按钮。车内乘客全都说自己没有被咬，可车载系统提示：第一名感染者正以员工权限登录终点站控制台。更糟的是，上一趟列车的到站记录写着‘明天早晨’。",
        "fact": "感染源来自被掩盖的地下实验冷链，而终点站的换气系统会在黎明前把孢子送往全城。",
        "deadline": "黎明换气程序", "humor": "笑点来自自动售票机仍坚持推荐‘双人甜蜜出行票’，以及广播用最礼貌的语气提醒感染者请勿倚靠车门。",
        "locations": [
            ("terminal_platform", "零号线终点站台", "末班车门开着，黄色安全线内外都没有安全。"),
            ("dispatch_center", "调度中心", "每一块屏幕都显示不同的到站时间。"),
            ("sealed_carriage", "封锁车厢", "座椅下有一串没有人承认的冷链标签。"),
            ("maintenance_tunnel", "检修隧道", "隧道壁上的应急灯每隔十米少一盏。"),
            ("ticket_hall", "地下票厅", "闸机还在收票，却不再放人出去。"),
            ("ventilation_room", "换气机房", "风机启动倒计时停在五小时五十九分。"),
            ("abandoned_platform", "废弃三号站台", "旧线路图上多出一座从未命名的站。"),
            ("medical_kiosk", "站内急救点", "药柜里少的不是药，是消毒记录。"),
            ("control_cab", "列车驾驶室", "自动驾驶还在等待一位不存在的司机确认。"),
            ("storm_drain", "雨水排放渠", "水流把一枚员工门卡冲向城外。"),
            ("freight_siding", "冷链货运侧线", "最后一节货厢没有出现在官方编组表上。"),
            ("substation", "牵引变电所", "停电能封住闸门，也可能困死里面的人。"),
            ("staff_locker", "员工更衣室", "每个柜门上都贴着今晚的值班表。"),
            ("surface_exit", "封闭地面出口", "上面是安静的夜市，下面的广播听得一清二楚。"),
            ("command_bus", "应急指挥车", "车已到站，车上的命令却来自一小时前。"),
        ],
        "people": [
            ("苏晚晴", "列车司机", "把还活着的乘客带出车厢", "她在发车前看见实验样本被偷偷卸下"),
            ("贺临川", "疾控调查员", "锁定感染方式", "他并未获授权进入站内"),
            ("陆苒", "夜市摊主", "找到失联的弟弟", "弟弟在冷链公司实习"),
            ("程野", "地铁维修工", "守住变电所", "他的门卡就是系统提示的员工权限"),
            ("魏青", "站内保安", "维持隔离线", "她瞒着所有人自己被轻微抓伤"),
            ("罗远", "冷链公司主管", "把货厢从记录里抹掉", "他收到过停止运输的邮件"),
            ("方乐", "医学研究生", "验证样本是否会空气传播", "她曾参与过早期项目"),
            ("杜宁", "广播员", "维持乘客秩序", "广播后台有一份强制疏散脚本"),
            ("陈锡", "失联实习生", "活着离开货运侧线", "他知道货厢不是意外进入地铁"),
        ],
        "cover": "zombie-station-cover-v1.png",
        "cover_alt": "末班地铁驶入昏暗终点站，成年调度员隔着控制台看向封锁车厢和红色换气倒计时",
    },
    {
        "key": "war_radio_v1", "slug": "frontline-radio", "title": "前线电台：停火前我必须播出真相",
        "genre": "war_drama", "tags": ["战争", "电台", "群像", "抉择"],
        "theme": {"accent": "#9c4435", "background": "#24262a", "surface": "#e7e0d5", "text": "#222326"},
        "world": "虚构的北境·阿斯塔前线", "role": "战地公共电台技术员", "age": 31,
        "hook": "停火协议将在日出签署，电台却收到军部命令：立刻播出一段伪造的投降声明。你一打开备用频段，就听见被围困医院的真实求救；如果不播，双方都会以为对方先撕毁停火。",
        "fact": "伪造声明的目的不是赢下一场战斗，而是让停火失败后某军火商的秘密运输继续通行。",
        "deadline": "日出停火签署", "humor": "笑点只来自电台旧设备的倔脾气和士兵对军用说明书的吐槽，不嘲笑伤者、平民或战争受害者。",
        "locations": [
            ("radio_bunker", "前线地下电台", "铁门上贴着‘保持中立’，发射机旁却放着三份命令。"),
            ("antenna_ridge", "天线山脊", "风能把信号送远，也能把人暴露在望远镜里。"),
            ("field_hospital", "野战医院", "发电机每停一次，病房就少一盏灯。"),
            ("ceasefire_tent", "停火谈判帐篷", "桌上两份地图的桥梁位置并不相同。"),
            ("supply_depot", "补给仓库", "医疗箱底下压着一份不该出现在前线的运单。"),
            ("old_town_square", "旧城广场", "钟楼停在炮击开始的那一分钟。"),
            ("river_crossing", "北河渡口", "停火生效前最后一批平民还在排队过河。"),
            ("press_truck", "独立记者转播车", "车上的卫星链路能播出真相，也能被定位。"),
            ("signal_tower", "废弃信号塔", "塔顶挂着一面没有标识的白旗。"),
            ("command_post", "联合指挥所", "每个人都说自己只是在执行上级命令。"),
            ("orchard", "焦土果园", "树下埋着一台仍能读取的战地录音机。"),
            ("rail_yard", "边境货运站", "一列无编号列车正在等待天亮。"),
            ("civilian_shelter", "市民避难所", "收音机是他们唯一知道外面发生什么的窗口。"),
            ("memorial_wall", "失踪者纪念墙", "墙上的名字比官方名单多了七个。"),
            ("emergency_airstrip", "临时跑道", "一架医疗机只有在正确的频段听到口令才会降落。"),
        ],
        "people": [
            ("伊莲娜", "战地医生", "让医院撑到停火", "她保存了炮击坐标的原始记录"),
            ("阿迪尔", "独立记者", "拿到可公开核验的证据", "他的直播牌照已被双方吊销"),
            ("马库斯", "通信军官", "让伪造声明准时播出", "他不知道命令来自军火商中间人"),
            ("诺娅", "停火观察员", "确认两军都撤离桥头", "她发现己方地图被替换"),
            ("塔拉斯", "货运站长", "放走被扣的医疗货车", "无编号列车装的是武器部件"),
            ("萨米尔", "避难所志愿者", "让民众听到可靠消息", "他弟弟在对岸医院"),
            ("维拉", "电台主持人", "保持频道不断播", "她能识别伪造声明里的声音剪辑"),
            ("奥森", "退役爆破手", "清出天线山脊", "他曾炸过那座被标为安全的桥"),
            ("米娅", "翻译员", "对照两份协议文本", "其中一份少了平民撤离条款"),
        ],
        "cover": "war-radio-cover-v1.png",
        "cover_alt": "战地地下电台中，成年技术员调试旧发射机，远处日出前的山脊与红色停火倒计时同框",
    },
    {
        "key": "exiled_empress_v1", "slug": "exiled-empress", "title": "穿成废后：我先把冷宫改成朝堂",
        "genre": "historical_transmigration", "tags": ["穿越", "古装", "权谋", "逆袭"],
        "theme": {"accent": "#a52634", "background": "#eee2cf", "surface": "#fff9ed", "text": "#2b201b"},
        "world": "大晟·皇城冷宫", "role": "醒在废后身体里的现代档案员", "age": 27,
        "hook": "你睁眼时，废后诏书已经盖了印，三天后赐死。冷宫的门被锁住，门外却堆着六箱被内务府退回的赈灾账册。皇帝以为你会求情，他不知道你上辈子专门整理‘被人故意弄乱的纸’。",
        "fact": "废后案只是掩盖赈灾银流向的幌子，冷宫恰好是所有被退回文书的中转处。",
        "deadline": "三日赐死诏", "humor": "笑点来自冷宫嬷嬷把朝堂政治当成厨房排班，以及玩家用现代归档法逼疯只会背规矩的太监。",
        "locations": [
            ("cold_palace", "听雪冷宫", "门锁了，人却比宫里任何地方都多。"),
            ("abandoned_archive", "废档库", "退回的赈灾账册堆到能当墙。"),
            ("laundry_court", "浣衣院", "每块宫牌都会在这里留下洗不掉的墨迹。"),
            ("imperial_kitchen", "御膳房后库", "米袋上的封条比圣旨更诚实。"),
            ("palace_wall", "西宫墙夹道", "送泔水的车能进出，送人不能。"),
            ("ancestral_hall", "太庙偏殿", "旧皇后的画像背后藏着一份未烧尽的名册。"),
            ("censor_office", "都察院值房", "弹劾折子按颜色分筐，红筐从不进御前。"),
            ("market_gate", "西市宫门", "宫外商户等着收回被拖欠的赈济粮款。"),
            ("river_granary", "京畿漕仓", "账上满仓，地上只剩谷壳。"),
            ("empress_garden", "废苑", "花圃下埋着前朝的雨水管道。"),
            ("night_watch", "更房", "更牌能证明谁在什么时辰经过冷宫。"),
            ("medicine_store", "太医院药库", "赈灾药材的进出库数对不上。"),
            ("audience_hall", "承明殿", "所有人等着你跪下，没人等着你带账册进门。"),
            ("prison_annex", "女官禁室", "替人抄写诏书的女官被关在最里面。"),
            ("city_temple", "城隍庙赈棚", "真正挨饿的人知道哪一批粮从没到过。"),
        ],
        "people": [
            ("萧彻", "年轻皇帝", "让废后案尽快结束", "他收到的赈灾汇报是伪造的"),
            ("沈知微", "冷宫女官", "保住被关押的妹妹", "她抄过原始赈灾名册"),
            ("裴行简", "御史", "查清漕仓缺粮", "他曾投过废后弹劾票"),
            ("顾太后", "太后", "维持皇室体面", "她知道废后案被人利用"),
            ("陆昭仪", "新宠妃", "摆脱被当作棋子的处境", "她把一枚内库钥匙藏进香囊"),
            ("魏掌印", "内务府总管", "毁掉漕运账链", "退回冷宫的账册是他故意安排"),
            ("阿绫", "浣衣女", "拿回被克扣的工钱", "她见过假宫牌进出浣衣院"),
            ("周粮商", "京畿粮商", "拿到朝廷欠款", "他保留了一张双重签收单"),
            ("许嬷嬷", "冷宫掌事", "让冷宫的人活过冬天", "她有通往废苑的旧钥匙"),
        ],
        "cover": "exiled-empress-cover-v1.png",
        "cover_alt": "红墙冷宫中，成年废后穿素衣翻开赈灾账册，门外宫灯与三日赐死诏形成对峙",
    },
    {
        "key": "jade_gate_expedition_v1", "slug": "jade-gate-expedition", "title": "玉门地宫：第七码道门后没有死人",
        "genre": "tomb_expedition_mystery", "tags": ["地宫", "探险", "机关", "悬疑"],
        "theme": {"accent": "#2f8175", "background": "#12252a", "surface": "#e9e1cc", "text": "#1d2928"},
        "world": "河西·玉门山地宫保护区", "role": "文物应急勘探队领队", "age": 32,
        "hook": "山洪冲开封闭两千年的地宫入口，救援队的探测机器人传回一张新照片：第七道门后摆着今晚才发行的矿泉水。上面还有一串湿脚印，正从深处往外走。",
        "fact": "地宫并非单纯墓室，而是古代水利与天文观测站；现代盗采团伙利用旧泄水道提前进入并困住了人。",
        "deadline": "山洪回灌", "humor": "笑点来自严肃考古队被一只会叼走测距尺的洞穴狸花猫打乱节奏，以及机关说明被实习生误读成景区导览。",
        "locations": [
            ("flooded_entrance", "山洪入口", "探方边缘的泥水还在往石门里倒灌。"),
            ("jade_gate", "第一道玉门", "门缝的铜环比任何现代锁都干净。"),
            ("star_corridor", "星图长廊", "顶壁星图会随水位改变缺口的位置。"),
            ("wind_shaft", "通风竖井", "风从地下吹出，带着不属于古墓的柴油味。"),
            ("mirror_chamber", "镜室", "青铜镜照出的不是人影，是下一扇门的开法。"),
            ("water_clock_room", "水钟室", "水滴每错一拍，某条通道就会封死。"),
            ("seventh_gate", "第七道门", "现代矿泉水瓶就摆在门槛内侧。"),
            ("underground_wharf", "地下引水码头", "石舟槽里卡着一只新式头灯。"),
            ("bronze_workshop", "铜工坊", "古代模具和现代切割片放在同一张石案上。"),
            ("record_chamber", "刻石档案室", "墙上的灌溉图正好对应山外失踪的村庄。"),
            ("collapse_gallery", "坍塌回廊", "不能用爆破，只能听声找空腔。"),
            ("emergency_camp", "保护区应急营地", "所有人的对讲机都收得到陌生频道。"),
            ("old_quarry", "废弃采石场", "盗采车辙在雨里还没完全消失。"),
            ("ridge_observatory", "山脊观测点", "无人机能看到地宫泄水口的真实位置。"),
            ("rescue_shelter", "临时避险洞", "被困的人留下了三段不同时间的求救录音。"),
        ],
        "people": [
            ("秦野", "地质工程师", "阻止山洪灌入", "他发现泄水道被人为改过"),
            ("林照", "文物修复师", "保护刻石与镜室", "她能读出墙上被补刻的字"),
            ("马隼", "当地向导", "找到失踪的采石工", "他弟弟曾被盗采团伙雇佣"),
            ("周澈", "水利史研究员", "解开水钟室", "他私下带来了未获批的旧拓片"),
            ("何颖", "应急医生", "把被困者安全转移", "她收到过一通来自地宫内的现代电话"),
            ("罗竞", "保护区安保", "封住盗采出口", "他的巡逻记录被人替换过"),
            ("苏可", "无人机操作员", "定位泄水口", "她的无人机拍到营地里有人提前拿走头灯"),
            ("段木匠", "退休石匠", "识别石门受力", "他父亲参与过早年非法开凿"),
            ("周班主", "盗采团伙中间人", "带走地宫里的现代证据", "他也被困在第七道门之后"),
        ],
        "cover": "jade-gate-expedition-cover-v1.png",
        "cover_alt": "河西山地地宫内，成年勘探队员举着头灯面对第七道石门，门后有现代矿泉水和湿脚印",
    },
    {
        "key": "room_404_v1", "slug": "room-404", "title": "404客房：入住的人都说自己没死",
        "genre": "supernatural_horror", "tags": ["灵异", "酒店", "推理", "惊悚"],
        "theme": {"accent": "#6c4c86", "background": "#1d1b28", "surface": "#f0ebdf", "text": "#211d2a"},
        "world": "雾港·云岚旅店", "role": "接手夜班的代班经理", "age": 28,
        "hook": "凌晨四点零四分，前台电话同时响起四次。四个住客都在问同一件事：为什么登记簿把他们的退房时间写成了十年前？而404的房门，从里面反锁着，却刚刚收到一份今天的外卖。",
        "fact": "旅店不是困住亡者，而是保留未被记录的事故证词；有人试图利用它抹去十年前渡轮事故的幸存者。",
        "deadline": "第四次钟响", "humor": "笑点来自旅店智能客服坚持给鬼住客推送延迟退房优惠，以及老电梯对每个灵异事件都要求填写故障单。",
        "locations": [
            ("lobby", "云岚旅店前台", "登记簿总会在你眨眼时多一行字。"),
            ("room_404", "404客房", "门牌完好，房号在系统里却不存在。"),
            ("old_elevator", "老式电梯", "它只会停在有人说出真名的楼层。"),
            ("boiler_room", "地下锅炉房", "蒸汽管里偶尔传出渡轮鸣笛。"),
            ("rooftop_pool", "封闭天台泳池", "水面映出雾港十年前的灯塔。"),
            ("laundry", "地下洗衣房", "湿床单上有一串从海里走来的脚印。"),
            ("staff_office", "夜班办公室", "前任经理留下的交接本从第七页开始被撕掉。"),
            ("ferry_terminal", "旧渡轮码头", "事故纪念碑上少了四个名字。"),
            ("archive", "市政事故档案馆", "原始乘客名单被改过装订顺序。"),
            ("chapel", "码头小礼拜堂", "失踪者家属每年都在这里点同样数量的蜡烛。"),
            ("kitchen", "旅店后厨", "外卖袋上的收货人写着404住客的名字。"),
            ("service_stairs", "消防楼梯", "每走一层，墙上的日期就往回跳一年。"),
            ("fog_alley", "浓雾后巷", "送餐员从这里进来，却说没见过正门。"),
            ("harbor_watch", "港务塔", "航行日志记得那晚的雾，却不记得那艘船。"),
            ("mirror_suite", "镜面套房", "镜子里的人会先开口，但不一定会说谎。"),
        ],
        "people": [
            ("程雾", "404住客", "找回自己的真实姓名", "她是事故幸存者，不是亡者"),
            ("许言", "夜班保安", "守住旅店的门", "他十年前在渡轮码头值勤"),
            ("林蓁", "事故记者", "重开调查报道", "她曾发表过错误的死亡名单"),
            ("周阿姨", "旅店厨师", "让每个住客吃到热饭", "她认得每一位从登记簿出现的人"),
            ("韩牧", "港务处主任", "维持旧案结论", "他签过删除幸存者信息的文件"),
            ("唐小满", "外卖骑手", "弄清自己为何会送到404", "她的定位记录总在十年前的码头"),
            ("李修", "前任经理", "完成未写完的交接", "他没有离职，只是被登记为退房"),
            ("苏姨", "家属代表", "找到少掉的四个名字", "她手里有未公开的录音带"),
            ("白舟", "旅店维修工", "修好锅炉与电梯", "他的钥匙能打开每一层不存在的门"),
        ],
        "cover": "room-404-cover-v1.png",
        "cover_alt": "雾港老旅店的404房门在走廊尽头微开，成年夜班经理拿着登记簿，门缝透出海雾与暖光",
    },
    {
        "key": "jiangshi_courier_v1", "slug": "jiangshi-courier", "title": "夜班赶尸人：客户在棺材里给我差评",
        "genre": "jiangshi_comedy", "tags": ["僵尸", "民俗", "喜剧", "冒险"],
        "theme": {"accent": "#d28b2c", "background": "#162229", "surface": "#f3ead6", "text": "#2b211b"},
        "world": "南岭·夜行驿道", "role": "刚接班的民俗遗体护送员", "age": 25,
        "hook": "你接到第一单夜班护送，棺材里的‘客户’敲了三下盖板，并通过驿站小程序给了你一星评价：步子太快、湿度太大、请在天亮前把我送回家。可导航显示，他的家已经在三十年前被一座水库淹没。",
        "fact": "客户并非失控怪物，而是被非法迁坟团伙冒用身份的证人；送达路线隐藏着被淹古镇的证据。",
        "deadline": "天亮前回魂", "humor": "笑点来自僵尸客户严肃投诉服务细节、纸人导航总爱带错路，以及传统规矩与现代物流条款互相打架。",
        "locations": [
            ("night_station", "夜行驿站", "扫码枪能识别纸钱，却识别不了棺材里的投诉。"),
            ("coffin_cart", "避光运棺车", "车厢温湿度显示比乘客还挑剔。"),
            ("bamboo_bridge", "竹影桥", "桥上不能回头，桥下却有一盏在追车的灯。"),
            ("paper_shop", "纸扎铺", "老板卖的纸手机会真的响一次。"),
            ("old_temple", "山神旧庙", "香灰里压着一张水库施工图。"),
            ("reservoir_edge", "沉水库岸", "水位退下去时会露出半截牌坊。"),
            ("village_square", "旧镇牌楼", "子夜后，淹没的街道会在雾里显形。"),
            ("funeral_parlor", "白事铺后堂", "每份订单都有两张不同的死亡证明。"),
            ("cliff_path", "崖边驿道", "车辙只进不出，像有谁一直在绕圈。"),
            ("abandoned_school", "旧镇小学", "黑板上还写着三十年前的放假通知。"),
            ("toll_booth", "夜路收费亭", "收费员只收旧铜钱，不收现金。"),
            ("watch_house", "守夜人小屋", "墙上挂着历代赶尸人的路线牌。"),
            ("dam_control", "水库闸房", "闸门日志有一页被人撕去。"),
            ("market_lane", "阴阳集巷", "卖早餐的摊主比所有人都清楚谁还活着。"),
            ("ancestral_hall", "陈家祠堂", "客户说这里不是终点，是他要作证的地方。"),
        ],
        "people": [
            ("陈叙白", "棺中客户", "在天亮前找回身份", "他并没有死，只是被人伪造死亡"),
            ("阿梨", "纸扎铺老板", "找回被迁走的祖坟", "她会修真正能通话的纸手机"),
            ("马师傅", "老赶尸人", "教你安全过桥", "他知道水库下的旧路线"),
            ("周小舟", "水库工程师", "阻止非法放水", "闸房日志是他父亲改过的"),
            ("白阿婆", "守夜人", "保住旧镇牌楼", "她曾给陈叙白开过死亡证明"),
            ("贺三", "迁坟商人", "把客户送去错误祠堂", "他靠伪造死亡证明赚钱"),
            ("李春花", "阴阳集摊主", "找回欠下的货款", "她见过盗运队半夜过桥"),
            ("沈巡警", "山区民警", "确认失踪案", "他不信鬼但信完整证据"),
            ("小满", "实习护送员", "拿到正式资格", "她误把客户的投诉设置成公开评价"),
        ],
        "cover": "jiangshi-courier-cover-v1.png",
        "cover_alt": "南岭夜路上，成年护送员推着避光运棺车穿过竹桥，棺盖露出一只拿着评价单的手，远处是月下水库",
    },
    {
        "key": "heartbeat_countdown_v1", "slug": "heartbeat-countdown", "title": "心动倒计时：前任和新同事都能听见我心声",
        "genre": "romance_comedy", "tags": ["恋爱", "轻喜剧", "职场", "都市"],
        "theme": {"accent": "#d34e75", "background": "#fff2f2", "surface": "#ffffff", "text": "#35242c"},
        "world": "江城·声波科技节", "role": "临时接手发布会的产品策划", "age": 27,
        "hook": "发布会前一小时，你测试情绪同步耳机时出了故障：前任和新同事都能听见你的心声。更糟的是，两人的设备权限都不能被你远程关闭，而全场媒体正等着看你们演示‘真诚沟通’。",
        "fact": "故障不是读心魔法，而是测试版把未加密的内部备注误路由给了两名同意参与试验的佩戴者；三人必须共同决定公开、修复或撤回产品。",
        "deadline": "发布会开场", "humor": "笑点来自内心吐槽被精准外放、产品经理拿隐私条款当情话解释，以及三位成年人主动设置边界后的尴尬合作。",
        "locations": [
            ("demo_stage", "科技节主舞台", "大屏幕倒数一小时，台词提词器却显示你的心里话。"),
            ("sound_lab", "声波实验室", "三副耳机的连接线像一场不合时宜的红线。"),
            ("backstage", "发布会后台", "每个人都在问产品能不能上线，没有人问能不能先下线。"),
            ("coffee_bar", "园区咖啡吧", "前任点了你三年前的口味，店员尴尬得像系统提示。"),
            ("rooftop", "创意园天台", "适合谈心，也适合躲开媒体的长镜头。"),
            ("privacy_office", "数据合规办公室", "一张同意书能救产品，也能让关系更难装糊涂。"),
            ("podcast_booth", "播客录音棚", "安静得能听见谁在偷偷深呼吸。"),
            ("archive_room", "产品档案室", "第一版测试笔记写着一个被划掉的警告。"),
            ("riverwalk", "江边步道", "晚风很适合道歉，不适合继续假装没听见。"),
            ("investor_lounge", "投资人休息区", "他们只问数据增长，不懂谁愿意被听见。"),
            ("equipment_store", "器材库", "备用耳机缺的刚好是第三副。"),
            ("subway_exit", "园区地铁口", "前任说赶车，脚步却一直没动。"),
            ("legal_room", "法务小会议室", "解除试验需要每位参与者明确确认。"),
            ("food_truck", "夜市餐车", "新同事点错辣度后还嘴硬说自己没哭。"),
            ("quiet_room", "无声休息室", "只有在这里，三个人的心声才不会被系统记录。"),
        ],
        "people": [
            ("顾言", "前任摄影师", "把未完成的纪录片做完", "他申请测试是为拍用户体验，不是为接近你"),
            ("陆星河", "新同事工程师", "修好同步协议", "他早就发现权限路由异常却怕影响发布"),
            ("许棠", "合规负责人", "保护所有测试者的选择权", "她也曾因产品泄露受过伤"),
            ("周柚", "发布会主持人", "救回现场节奏", "她能把任何社死现场说成互动环节"),
            ("沈峤", "公司创始人", "按时发布产品", "他签过过度采集的早期方案"),
            ("林简", "产品经理", "让演示成功", "他的备注正是串线的技术源头"),
            ("季然", "投资人代表", "评估产品风险", "她愿意支持撤回发布"),
            ("唐青", "播客主理人", "拿到真实访谈", "她被误送过一段心声样本"),
            ("吴沐", "实习设计师", "修复演示界面", "她偷偷加了一个一键静音按钮"),
        ],
        "cover": "heartbeat-countdown-cover-v1.png",
        "cover_alt": "科技发布会后台，成年产品策划戴着耳机站在大屏倒计时前，前任与新同事隔着透明玻璃同时听见提示波形",
    },
    {
        "key": "abyss_oxygen_v1", "slug": "abyss-oxygen", "title": "深海城停电后，氧气只剩六小时",
        "genre": "deep_sea_disaster", "tags": ["灾难", "科幻", "深海", "生存"],
        "theme": {"accent": "#1d98a8", "background": "#071a26", "surface": "#e2eff2", "text": "#122833"},
        "world": "深海一号·海沟居住城", "role": "氧循环维护主管", "age": 34,
        "hook": "海沟城突然全域断电，市长宣布氧气够撑二十四小时。你却在手动阀门上看见一个更诚实的数字：六小时。有人提前把公共氧仓转给了只供贵宾使用的观景穹顶。",
        "fact": "断电由地面公司远程触发，目的是制造撤离配额危机并掩盖深海采矿事故。",
        "deadline": "氧循环耗尽", "humor": "笑点来自深海城的礼宾机器人仍在播报‘请欣赏海景’，以及所有人争论谁该修电时一只清洁蟹抢走了关键螺丝。",
        "locations": [
            ("oxygen_core", "氧循环核心", "阀门显示的六小时比任何演讲都可靠。"),
            ("observation_dome", "贵宾观景穹顶", "玻璃外是深海，玻璃内是被锁住的氧仓。"),
            ("power_spine", "主电力脊柱", "每重启一段，就会让另一段熄灭。"),
            ("habitat_ring", "居民舱环", "家庭氧气表正在一个接一个变黄。"),
            ("sub_dock", "潜艇码头", "两艘救生潜艇只有一艘满电。"),
            ("mining_tunnel", "采矿联络隧道", "事故报告被标成了设备维护。"),
            ("water_farm", "海藻水培区", "能临时增氧，也需要大量电力。"),
            ("med_bay", "深海医务舱", "医生必须先决定哪些设备不断电。"),
            ("city_hall", "海城指挥厅", "公开广播和内部配给表完全不同。"),
            ("data_well", "海底数据井", "地面公司的远程指令还在重复发送。"),
            ("maintenance_shaft", "外壳检修井", "外部压力让每一次开门都要付出代价。"),
            ("school_pod", "居民学校舱", "孩子们正在练习一次并不存在的安全演习。"),
            ("archive_bubble", "旧城档案泡", "第一批移民留下了备用氧仓设计。"),
            ("waste_heat", "余热回收站", "一组废热机能给海藻区续命。"),
            ("escape_lock", "紧急气闸", "撤离名单已经生成，却没有署名。"),
        ],
        "people": [
            ("陈汐", "城市医生", "让医务舱不断电", "她知道市长家属不在居民舱"),
            ("贺舟", "潜艇船长", "带最多人安全上浮", "他的潜艇电池被人调换过"),
            ("伊芙", "地面公司代表", "维持撤离秩序", "她收到过远程断电计划"),
            ("方遥", "海藻研究员", "用水培区补氧", "她发现采矿废液污染了水源"),
            ("周尧", "市长助理", "保住观景穹顶配额", "他签过秘密氧仓转移单"),
            ("白岚", "维修潜水员", "修复外壳线路", "她在采矿隧道发现受困工人"),
            ("阿成", "居民代表", "公开真实配给表", "他能组织居民轮流手动发电"),
            ("罗砂", "矿工", "救出隧道同伴", "事故并非天然塌方"),
            ("米拉", "档案管理员", "找到旧设计", "她保留了地面公司删除的图纸"),
        ],
        "cover": "abyss-oxygen-cover-v1.png",
        "cover_alt": "深海居住城的氧循环核心前，成年维护主管拧动手动阀门，窗外蓝黑海沟与六小时氧气倒计时相映",
    },
    {
        "key": "live_court_v1", "slug": "live-court", "title": "全网审判：我在直播庭审里翻案",
        "genre": "legal_thriller", "tags": ["庭审", "直播", "反转", "悬疑"],
        "theme": {"accent": "#4c6589", "background": "#eef0f4", "surface": "#ffffff", "text": "#1c2635"},
        "world": "澄江市·网络法庭", "role": "被判定为诈骗主犯的普通程序员", "age": 30,
        "hook": "你的直播庭审刚开场，百万网友已经投出九成有罪。法官宣布最后陈述只有二十分钟，你却发现庭审证据里那段‘你的录音’说错了自己工位旁唯一会响的老空调型号。真正的录音者，从没进过你的办公室。",
        "fact": "诈骗案被用合成录音和伪造登录日志拼接，真正受益者利用公开庭审的舆论压力迫使关键证人沉默。",
        "deadline": "二十分钟最后陈述", "humor": "笑点来自法庭直播弹幕把专业术语听成菜名、书记员严肃纠正网友投票不等于证据，以及程序员对空调型号的执拗。",
        "locations": [
            ("live_court", "网络法庭主庭", "倒计时、证据屏和百万弹幕挤在同一面墙上。"),
            ("evidence_lab", "电子证据实验室", "一秒音频能被切成十种故事。"),
            ("old_office", "旧办公区", "那台老空调还在按错误的节奏响。"),
            ("data_center", "云端数据中心", "登录日志的时区比人更容易撒谎。"),
            ("public_defense", "公设辩护室", "律师只有二十分钟，也有二十个问题。"),
            ("witness_lounge", "证人等候室", "每扇门外都有人劝证人‘别惹麻烦’。"),
            ("media_hall", "媒体大厅", "采访灯比庭审灯更亮。"),
            ("bank_archive", "银行流水档案室", "转账路径在一笔退款处打了结。"),
            ("server_rooftop", "机房天台", "备份天线能播出原始时间戳。"),
            ("maintenance_room", "空调维修间", "报修单里藏着那天谁真正进过办公室。"),
            ("cyber_unit", "网安协作室", "他们能验证日志，也被上级要求保持中立。"),
            ("coffee_shop", "法院街咖啡店", "证人说愿意见你，但只在摄像头外。"),
            ("appeal_archive", "再审档案库", "三年前有一宗极像的案子被草草结案。"),
            ("control_booth", "直播导播间", "延迟十五秒，正好够人剪掉一句话。"),
            ("exit_steps", "法院台阶", "无罪或有罪，镜头都会在这里等你。"),
        ],
        "people": [
            ("梁默", "公设辩护律师", "在最后陈述前找到硬证据", "他曾输过一宗相似合成录音案"),
            ("苏青", "电子证据鉴定人", "验证录音真伪", "她的初稿被人删改过"),
            ("程铭", "检方技术顾问", "维护证据链可信度", "他发现时区错误却没有上报"),
            ("顾薇", "关键证人", "保护自己和弟弟", "她见过真正的操盘者"),
            ("何律", "直播平台主管", "不让庭审失控", "导播间存在十五秒人工延迟"),
            ("郑遥", "银行风控员", "找出退款节点", "他保留了未经脱敏的原始流水"),
            ("唐工", "空调维修员", "证明谁到过旧办公室", "他记得那天的工号并不属于玩家"),
            ("沈策", "投资公司负责人", "维持诈骗案结论", "合成录音的项目资金来自他"),
            ("米可", "法庭书记员", "确保程序完整", "她能调出被删的庭审校验日志"),
        ],
        "cover": "live-court-cover-v1.png",
        "cover_alt": "网络法庭中，成年程序员站在证据屏前，红色二十分钟倒计时与音频波形照亮直播庭审现场",
    },
]


EVENT_TYPES = [
    {"key": key, "importance": importance, "visibility": visibility}
    for key, importance, visibility in [
        ("MOVE", 0.05, "LOCAL"), ("CONVERSATION", 0.12, "LOCAL"), ("DEATH", 1.0, "PUBLIC"),
        ("RESCUE", 0.9, "LOCAL"), ("BETRAYAL", 0.95, "PRIVATE"), ("PROMISE", 0.55, "PRIVATE"),
        ("SECRET_DISCLOSURE", 0.9, "PRIVATE"), ("ITEM_ACQUIRED", 0.25, "PRIVATE"),
        ("NPC_APPROACH", 0.45, "LOCAL"), ("RUMOR_SPREAD", 0.4, "PUBLIC"),
        ("FACTION_MOVE", 0.6, "FACTION"), ("QUEST_OFFER", 0.32, "LOCAL"),
        ("DISCOVERY", 0.65, "PRIVATE"), ("ENVIRONMENT_SHIFT", 0.45, "PUBLIC"),
        ("CONFRONTATION", 0.75, "LOCAL"), ("FORESHADOWING", 0.25, "LOCAL"),
    ]
]
ALLOWED = [row["key"] for row in EVENT_TYPES if row["key"] not in {"MOVE", "CONVERSATION", "ITEM_ACQUIRED"}]


def dump(root: Path, name: str, value: dict[str, Any]) -> None:
    (root / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def make_locations(spec: dict[str, Any]) -> dict[str, Any]:
    rows = []
    hub = spec["locations"][0][0]
    for index, (key, name, description) in enumerate(spec["locations"]):
        travel = {hub: 3} if index else {other[0]: 3 + (position % 5) for position, other in enumerate(spec["locations"][1:])}
        rows.append({"key": key, "name": name, "type": "room" if index else "district", "parent": None,
                     "danger": 1 if index in {3, 6, 10, 14} else 0, "spirit_density": 1,
                     "description": description, "travel": travel})
    return {"location_types": [{"key": "district", "name": "区域"}, {"key": "room", "name": "场景"}], "locations": rows}


def make_characters(spec: dict[str, Any]) -> dict[str, Any]:
    keys = ["anchor", "rival", "ally", "witness", "gatekeeper", "broker", "outsider", "insider", "wildcard"]
    factions = ["organizer", "authority", "witnesses", "authority", "organizer", "outsiders", "witnesses", "organizer", "outsiders"]
    locations = [row[0] for row in spec["locations"]]
    rows = []
    for index, (name, role, goal, secret) in enumerate(spec["people"]):
        rows.append({
            "key": keys[index], "name": name, "type": "MAJOR_NPC" if index < 6 else "MINOR_NPC", "age": 24 + index,
            "gender": "female" if index % 2 == 0 else "male", "location": locations[(index + 1) % len(locations)],
            "faction": factions[index], "faction_rank": role, "realm": "ordinary", "realm_stage": "newcomer",
            "stats": {"strength": 10 + index % 4, "agility": 10 + (index + 1) % 4, "perception": 12 + index % 5,
                      "intelligence": 12 + (index + 2) % 5, "willpower": 12 + index % 4, "charisma": 10 + (index + 3) % 5},
            "background": f"{role}。在{spec['world']}的今晚，任何一个人都不能只靠旁观离开。",
            "personality": {"traits": {"guarded": 0.65, "driven": 0.72}, "values": ["真相", "活下去"],
                            "taboos": ["替人背锅"], "speech_style": "短句、给出能核验的细节，不替任何人做决定", "risk_tolerance": 0.55},
            "emotion": {"dominant": "tense", "valence": -0.15, "arousal": 0.6, "intensity": 0.55},
            "long_term_goal": goal, "short_term_goals": [goal, "在倒计时结束前确认谁在说谎"],
            "schedule": {"default": "work", "slots": [{"phase": "morning", "activity": "work", "location": locations[(index + 1) % len(locations)]},
                                                       {"phase": "night", "activity": "rest", "location": locations[(index + 2) % len(locations)]}]},
            "items": [], "skills": ["investigation"] if index in {0, 2, 3, 6} else ["negotiation"],
            "reputation": {"global": 10 + index * 3, "by_faction": {factions[index]: 45 + index * 3}},
            "secret": secret, "capabilities": ["观察", "交涉", "行动"],
        })
    relationships = []
    for index, key in enumerate(keys):
        relationships.append({"a": key, "b": "player", "affection": 0, "trust": 8 - index * 2,
                              "respect": 5 - index, "suspicion": 15 + index * 4, "familiarity": 8 + index,
                              "boundaries": 60})
    return {"characters": rows, "relationships": relationships}


def make_facts(spec: dict[str, Any]) -> dict[str, Any]:
    return {"facts": [
        {"key": "fact_hook", "statement": spec["fact"], "truth_value": True, "scope": "WORLD", "sensitivity": 0.8,
         "related": ["player", "anchor", "rival"],
         "initial_knowledge": {"player": {"state": "KNOWN", "confidence": 1, "source": "DOCUMENT"},
                               "anchor": {"state": "KNOWN", "confidence": 0.9, "source": "WITNESSED"}}},
        {"key": "fact_hidden_operator", "statement": f"有人正利用{spec['deadline']}把所有人的选择推向同一条错误路线。", "truth_value": True,
         "scope": "FACTION", "sensitivity": 0.92, "related": ["rival", "gatekeeper"],
         "initial_knowledge": {"rival": {"state": "KNOWN", "confidence": 1, "source": "SEED"},
                               "player": {"state": "SUSPECTED", "confidence": 0.45, "source": "INFERRED"}}},
        {"key": "fact_missing_record", "statement": "关键记录被分成了纸质、设备和目击三个部分，单独任何一份都不足以定案。", "truth_value": True,
         "scope": "WORLD", "sensitivity": 0.55, "related": ["ally", "witness"],
         "initial_knowledge": {"ally": {"state": "KNOWN", "confidence": 1, "source": "SEED"}}},
        {"key": "fact_ally_boundary", "statement": "每位盟友都可以拒绝高风险要求；合作必须说明代价、退出方式和信息用途。", "truth_value": True,
         "scope": "WORLD", "sensitivity": 0.1, "related": ["player", "anchor", "ally"],
         "initial_knowledge": {"player": {"state": "KNOWN", "confidence": 1, "source": "SEED"}}},
        {"key": "fact_public_story", "statement": "公开版本看似完整，但关键时间戳与现场记录不能同时成立。", "truth_value": True,
         "scope": "WORLD", "sensitivity": 0.65, "related": ["outsider", "insider"],
         "initial_knowledge": {"outsider": {"state": "KNOWN", "confidence": 0.8, "source": "DOCUMENT"}}},
        {"key": "fact_exit_cost", "statement": "最容易离开的路线会把代价转移给留下的人。", "truth_value": True, "scope": "WORLD", "sensitivity": 0.7,
         "related": ["player", "wildcard"], "initial_knowledge": {"wildcard": {"state": "KNOWN", "confidence": 1, "source": "WITNESSED"}}},
    ]}


def make_threads(spec: dict[str, Any]) -> dict[str, Any]:
    threads = [
        ("thread_hook", "开场的不可逆事件", "谁设下了第一道局", "CONFRONTATION"),
        ("thread_record", "被拆开的关键记录", "三份记录如何互相核验", "DISCOVERY"),
        ("thread_alliance", "每个人的退出条件", "谁会在压力下倒向另一边", "PROMISE"),
        ("thread_operator", "躲在规则后的人", "谁从错误路线获利", "SECRET_DISCLOSURE"),
        ("thread_clock", spec["deadline"], "倒计时结束时会发生什么", "ENVIRONMENT_SHIFT"),
        ("thread_verdict", "最后的公开选择", "真相应被谁听见、怎样被使用", "FACTION_MOVE"),
    ]
    rows = []
    for index, (key, name, question, event_type) in enumerate(threads):
        rows.append({
            "key": key, "name": name, "status": "active", "importance": 0.88 + (index % 2) * 0.05, "stage": 0,
            "participants": ["player", ["anchor", "ally", "witness", "gatekeeper", "rival", "outsider"][index]],
            "unresolved_questions": [question], "foreshadowing": ["一条可核验的细节与公开说法不一致", "有人提前准备了错误的出口"],
            "related_facts": ["fact_hook" if index == 0 else "fact_missing_record", "fact_hidden_operator" if index in {3, 4, 5} else "fact_public_story"],
            "next_beat_hint": f"围绕‘{name}’的下一步不再只是解释，而会改变{spec['world']}里谁拥有决定权。",
            "escalation_pressure": 0.82 + index * 0.02,
            "scheduled_beats": [
                {"at_minutes_from_start": 12 + index * 42, "event_type": event_type, "beat": f"{name}出现第一条无法忽略的证据。", "participants": ["player"]},
                {"at_minutes_from_start": 32 + index * 42, "event_type": "DISCOVERY", "beat": "第二份记录与此前的版本互相矛盾。", "participants": ["ally"]},
                {"at_minutes_from_start": 54 + index * 42, "event_type": "CONFRONTATION", "beat": "有人要求玩家立刻选择公开、隐瞒或交换条件。", "participants": ["rival"]},
            ],
        })
    quests = []
    for index, (thread_key, _, _, _) in enumerate(threads):
        for step in range(2):
            quest_key = f"quest_{index + 1}_{step + 1}"
            quests.append({
                "key": quest_key, "name": f"{threads[index][1]}·{'取证' if step == 0 else '决定'}", "giver": ["anchor", "ally", "witness", "gatekeeper", "outsider", "insider"][index],
                "status": "offered", "goal": {"type": "investigate" if step == 0 else "decide", "location": spec["locations"][(index * 2 + step) % len(spec["locations"])][0]},
                "constraints": {"deadline_minutes": 90 + index * 55 + step * 20},
                "rewards": {"resource": {"clue": 8 + index * 2 if step == 0 else "resolve"}},
                "failure_conditions": ["deadline_passed", "evidence_destroyed" if step == 0 else "choice_taken_by_other"],
                "world_consequences": {"on_success": {"advance_thread": thread_key}}, "plot_thread": thread_key,
            })
    clocks = [
        {"key": "clock_deadline", "name": spec["deadline"], "kind": "deadline", "thread": "thread_clock", "segments": 6,
         "minutes_per_segment": 60, "consequence": "倒计时归零，最危险的默认方案会自动执行。"},
        {"key": "clock_truth", "name": "可核验证据链", "kind": "project", "thread": "thread_record", "segments": 6,
         "consequence": "纸质记录、设备痕迹和目击证词必须相互印证。"},
        {"key": "clock_trust", "name": "临时同盟", "kind": "danger", "thread": "thread_alliance", "segments": 5,
         "consequence": "没有被说明代价的合作会在压力下瓦解。"},
    ]
    return {"plot_threads": rows, "quests": quests, "clocks": clocks}


def make_pack(spec: dict[str, Any]) -> dict[str, Any]:
    initial = spec["locations"][0][0]
    endings = [
        {"key": "ending_truth", "type": "independent", "title": "把真相送到该去的人手里", "priority": 95,
         "epilogue": "你没有替任何人宣布结论，却让每一份原始记录都回到能被核验的位置。局面由此被改写。",
         "condition": {"op": "eq", "args": [{"op": "get", "args": ["quests.quest_2_1.status"]}, "completed"]}},
        {"key": "ending_alliance", "type": "bond", "title": "留下的人一起决定", "priority": 85,
         "epilogue": "你没有独自成为英雄。每个知道代价的人都亲手确认了自己的选择，临时同盟变成了真正的承担。",
         "condition": {"op": "and", "args": [{"op": "eq", "args": [{"op": "get", "args": ["quests.quest_3_2.status"]}, "completed"]}, {"op": "eq", "args": [{"op": "get", "args": ["quests.quest_5_1.status"]}, "completed"]}]}},
        {"key": "ending_exit", "type": "independent", "title": "从错误剧本里离开", "priority": 70,
         "epilogue": "你拒绝用另一个谎言换安全出口。离开时局势仍然复杂，但没有人能再替你写下一步。",
         "condition": {"op": "eq", "args": [{"op": "get", "args": ["quests.quest_6_2.status"]}, "completed"]}},
        {"key": "ending_default", "type": "other", "title": "默认方案", "priority": 20,
         "epilogue": "倒计时替所有人做了选择。最容易执行的版本赢了，真正的问题被留给后来的人。",
         "condition": {"op": "eq", "args": [{"op": "get", "args": ["quests.quest_5_2.status"]}, "failed"]}},
    ]
    return {
        "key": spec["key"], "name": spec["title"], "genre": spec["genre"], "version": "1.0.0", "engine_min_version": "0.2.0",
        "primary_progression_key": "agency",
        "attribute_definitions": [{"key": "composure", "label": "定力", "type": "number"}, {"key": "investigation", "label": "调查", "type": "number"},
                                  {"key": "survival", "label": "应变", "type": "number"}, {"key": "persuasion", "label": "交涉", "type": "number"}],
        "resource_definitions": [{"key": "health", "label": "状态", "minimum": 0, "maximum": 100, "default": 100},
                                 {"key": "clue", "label": "线索", "minimum": 0, "maximum": 100, "default": 20},
                                 {"key": "resolve", "label": "意志", "minimum": 0, "maximum": 100, "default": 65},
                                 {"key": "danger", "label": "风险", "minimum": 0, "maximum": 100, "default": 25}],
        "progression_definitions": [{"key": "agency", "label": "行动权", "tiers": [{"key": "caught", "label": "被卷入", "order": 0}, {"key": "informed", "label": "掌握线索", "order": 1}, {"key": "decisive", "label": "能够决定", "order": 2}]}],
        "player_fields": [{"key": "name", "label": "姓名", "type": "text", "required": True}, {"key": "age", "label": "年龄", "type": "integer", "required": True, "default": spec["age"], "minimum": 22, "maximum": 45},
                          {"key": "specialty", "label": "你的专长", "type": "choice", "required": True, "default": "analysis", "choices": [{"value": "analysis", "label": "分析·从混乱里找顺序"}, {"value": "negotiation", "label": "交涉·让人把条件说清"}, {"value": "field", "label": "现场·先让人活下来"}, {"value": "records", "label": "档案·知道纸不会自己撒谎"}]},
                          {"key": "personal_goal", "label": "你想保住什么", "type": "text", "required": True, "default": "让真相和人都能离开这里"}],
        "language": "zh-CN", "assets": [{"key": f"{spec['key']}_cover", "kind": "cover", "path": f"official/{spec['key']}/{spec['cover']}", "alt": spec["cover_alt"]}],
        "author_tests": [
            {"key": "opening_is_playable", "name": "开场知识与地点正确", "scenario": "main_story", "assertions": [{"path": "player.location", "op": "eq", "expected": initial}, {"path": "knowledge.player.fact_hook", "op": "eq", "expected": "KNOWN"}]},
            {"key": "truth_ending_starts_locked", "name": "结局不会在开场被误解锁", "scenario": "main_story", "assertions": [{"path": "endings.ending_truth.available", "op": "eq", "expected": False}]},
        ],
        "world": {"name": spec["world"], "description": spec["hook"], "start_location": initial, "world_seed_default": spec["key"].replace("_v1", "")},
        "story": {"title": spec["title"], "opening_location": initial, "premise": spec["hook"],
                  "opening_blueprint": {"player_context": f"玩家是{spec['role']}，先给出已知风险、可验证线索与{spec['deadline']}，而非要求凭空信任任何人。",
                                       "acts": [{"purpose": "前五十字给出不可逆危机", "must_show": [spec["hook"], "倒计时已经开始"], "comic_beat": spec["humor"]},
                                                {"purpose": "交代玩家为什么不能直接离开", "must_show": ["玩家掌握一条可核验事实", "至少一位盟友有自己的退出条件"], "comic_beat": "笑点只缓冲紧张，不取消后果。"},
                                                {"purpose": "把局部困境升级为公共选择", "must_show": ["公开说法出现矛盾", spec["deadline"]], "comic_beat": "荒唐的制度语言被现场现实拆穿。"}]},
                  "starter_items": [{"key": "case_file", "quantity": 1}, {"key": "access_badge", "quantity": 1}],
                  "player_template": {"constraints": {"minimum_age": 22, "maximum_age": 45}, "properties": {"role": spec["role"]}},
                  "relationship_boundaries": "所有主要角色均为成年人。亲密、合作与高风险请求都必须以明确同意、可退出和信息用途透明为前提；拒绝后不得强迫推进。",
                  "endings": endings},
        "narrative_style": {"language": "中文", "person": "第二人称", "tense": "现在时", "tone": f"高密度{spec['genre']}互动短剧：行动先于解释，反转必须由文件、权限、时序或人物选择回收。",
                            "target_length": 1300, "avoid_phrases": ["嘴角勾起一抹弧度", "空气仿佛凝固", "眼中闪过异色", "一切才刚刚开始"], "phrase_repeat_window": 10, "phrase_repeat_threshold": 2,
                            "pacing": "explosive_microdrama", "pacing_rules": ["开场五十字内给出危机、期限和可选择的第一步。", "每回合让权力、证据、路线或人物站位至少变化一项。", "反转需要此前出现的证据支撑，禁止凭空升级身份。"],
                            "guidance": ["少写围观、沉默和空泛惊讶，多写可见动作与可核验后果。", spec["humor"], "避免把受害者、伤病或创伤当成笑点。"]},
        "theme": spec["theme"],
        "vocabulary": {"profile_labels": {"health": "状态", "power": "线索", "age_suffix": "岁", "realm": "行动权", "root": "专长", "faction": "阵营", "male": "男", "female": "女", "unspecified": "未指定", "story_lead": "关键盟友", "no_story_lead": "尚未结盟", "absent": "当前不在场"},
                       "relationship_labels": {"affection": "好感", "trust": "信任", "respect": "尊重", "fear": "忌惮", "hatred": "敌意", "suspicion": "怀疑", "dependency": "依赖", "familiarity": "熟悉", "boundaries": "界限"},
                       "action_aliases": {"MOVE": ["前往", "进入", "离开"], "TALK": ["交谈", "说明", "交涉"], "ASK": ["追问", "质询"], "OBSERVE": ["观察", "检查", "核对"], "SEARCH": ["搜查", "查找", "调记录"], "USE_ITEM": ["使用", "出示", "提交"], "USE_SKILL": ["分析", "判断", "处理"], "REST": ["休息"], "WAIT": ["等待"]},
                       "status_labels": {"offered": "待处理", "active": "进行中", "completed": "已完成", "failed": "已失败", "expired": "已超时"}},
    }


def make_realms() -> dict[str, Any]:
    return {"progression_name": "行动权", "realms": [{"key": "ordinary", "name": "局中人", "order": 0, "stages": [{"key": "newcomer", "name": "被卷入", "order": 0}, {"key": "capable", "name": "能行动", "order": 1}], "power_coefficient": 1, "max_health": 100, "max_spiritual_power": 100, "lifespan_years": 100, "xp_to_next_stage": 100, "breakthrough_base_chance": 1}], "spiritual_roots": [{"key": "professional", "name": "专长", "speed": 1, "breakthrough_mod": 0, "weight": 1}], "mental_states": [{"key": "steady", "name": "冷静", "min": 0, "max": 1.01, "breakthrough_mod": 0}], "bottleneck": {"gain_on_failure": 0, "max": 0, "penalty_per_point": 0, "decay_per_month": 0}}


def make_rules() -> dict[str, Any]:
    return {"action_plan": {"max_total_minutes": 120}, "time_costs": {"TALK": {"min": 2, "max": 15}, "ASK": {"min": 2, "max": 15}, "OBSERVE": {"min": 1, "max": 10}, "SEARCH": {"min": 5, "max": 30}, "MOVE_LOCAL": {"min": 1, "max": 8}, "MOVE_REGIONAL": {"min": 8, "max": 30}, "USE_ITEM": {"min": 1, "max": 12}, "USE_SKILL": {"min": 5, "max": 25}, "REST": {"min": 10, "max": 60}, "WAIT": {"min": 3, "max": 45}, "CUSTOM": {"min": 2, "max": 30}},
            "relationship": {"dimensions": ["affection", "trust", "respect", "fear", "hatred", "suspicion", "dependency", "familiarity", "boundaries"], "ranges": {"affection": {"min": -100, "max": 100, "default": 0}, "trust": {"min": -100, "max": 100, "default": 0}, "respect": {"min": -100, "max": 100, "default": 0}, "fear": {"min": 0, "max": 100, "default": 0}, "hatred": {"min": 0, "max": 100, "default": 0}, "suspicion": {"min": 0, "max": 100, "default": 20}, "dependency": {"min": 0, "max": 100, "default": 0}, "familiarity": {"min": 0, "max": 100, "default": 0}, "boundaries": {"min": 0, "max": 100, "default": 55}}, "max_delta_per_event": {"trivial": 2, "minor": 6, "major": 20, "life_changing": 40}},
            "narrative": {"tension_start": 68, "tension_decay_per_day": 2, "tension_gain_by_importance": 16, "high_threshold": 82, "max_consecutive_high_turns": 4},
            "director": {"min_interval_turns": 1, "thread_patience_minutes": 50, "pacing_rules": ["每次介入必须改变证据、权限、路线或人物站位。", "不安排无后果的围观和惊呼。"], "high_importance_override": 0.85, "max_events_per_day": 28, "max_schedule_delay_minutes": 30, "allowed_event_types": ALLOWED},
            "simulation": {"tick_minutes": {"lod1": 10, "lod2": 30, "lod3": 120}, "max_materialized_events_per_jump": 96, "npc_goal_action_interval_minutes": 25},
            "auto_advance": {"max_steps": 4, "max_minutes": 45, "npc_llm_per_step": 0, "interrupt_importance": 0.65, "interrupt_health_loss": 0.15, "engaging_actions": ["TALK", "ASK", "SEARCH", "OBSERVE"], "hostile_actions": ["ATTACK", "STEAL"], "offer_events": ["QUEST_OFFER", "CONFRONTATION", "SECRET_DISCLOSURE", "BETRAYAL", "DEATH"]},
            "consistency": {"strict": True, "checks": ["alive", "location", "inventory", "knowledge", "faction", "time"]}}


def build(spec: dict[str, Any]) -> None:
    root = ROOT / spec["key"]
    if root.exists():
        raise RuntimeError(f"refusing to overwrite existing content pack: {root}")
    root.mkdir(parents=True)
    (root / "assets").mkdir()
    dump(root, "pack.yaml", make_pack(spec))
    dump(root, "calendar.yaml", {"epoch_label": "公历", "epoch_year": 2026, "minutes_per_hour": 60, "hours_per_day": 24, "days_per_month": 30, "months_per_year": 12, "day_phases": [{"key": "morning", "name": "上午", "start_hour": 6, "end_hour": 12}, {"key": "afternoon", "name": "下午", "start_hour": 12, "end_hour": 18}, {"key": "night", "name": "夜间", "start_hour": 18, "end_hour": 24}], "start_year": 2026, "start_month": 9, "start_day": 20, "start_hour": 20, "start_minute": 0, "format": "{year}年{month}月{day}日 {phase}"})
    dump(root, "realms.yaml", make_realms())
    dump(root, "rules.yaml", make_rules())
    dump(root, "locations.yaml", make_locations(spec))
    dump(root, "factions.yaml", {"factions": [{"key": "organizer", "name": "组织方", "type": "institution", "description": "掌握入口、流程与对外说法的一方。", "values": ["控制", "体面"], "goals": ["让默认方案执行"], "resources": {"money": 60, "information": 70, "influence": 65, "people": 55}, "relations": {"witnesses": -20}}, {"key": "authority", "name": "执行机构", "type": "institution", "description": "拥有程序、门禁或正式权限，但内部意见并不一致。", "values": ["秩序", "程序"], "goals": ["控制风险"], "resources": {"money": 45, "information": 65, "influence": 70, "people": 45}, "relations": {"outsiders": -10}}, {"key": "witnesses", "name": "现场见证者", "type": "civic", "description": "知道片段事实、需要被说明风险的人。", "values": ["安全", "真相"], "goals": ["活着离开"], "resources": {"money": 15, "information": 55, "influence": 30, "people": 80}, "relations": {"organizer": -20}}, {"key": "outsiders", "name": "外部变量", "type": "coalition", "description": "不完全站在任何一边，但能改变出口。", "values": ["自保", "交易"], "goals": ["获得关键材料"], "resources": {"money": 30, "information": 45, "influence": 40, "people": 35}, "relations": {"authority": -10}}]})
    dump(root, "characters.yaml", make_characters(spec))
    dump(root, "npc_templates.yaml", {"templates": {}})
    dump(root, "items.yaml", {"item_types": [{"key": "document", "name": "文件"}, {"key": "device", "name": "设备"}, {"key": "token", "name": "权限"}, {"key": "evidence", "name": "证据"}], "rarities": [{"key": "common", "name": "普通", "value_multiplier": 1}, {"key": "key_item", "name": "关键", "value_multiplier": 1}], "items": [{"key": "case_file", "name": "开场记录", "type": "document", "rarity": "key_item", "value": 0, "stackable": False, "description": "证明公开说法缺少关键页的初始材料。", "effects": {"quest_item": True}}, {"key": "access_badge", "name": "临时权限卡", "type": "token", "rarity": "key_item", "value": 0, "stackable": False, "description": "能进入一处限制区域，且会留下日志。", "effects": {"quest_item": True}}, {"key": "field_map", "name": "现场地图", "type": "document", "rarity": "common", "value": 0, "stackable": False, "description": "标着出口，也标着谁有资格使用出口。", "effects": {}}, {"key": "raw_log", "name": "原始日志", "type": "evidence", "rarity": "key_item", "value": 0, "stackable": False, "description": "未经剪辑的时间记录。", "effects": {"quest_item": True}}, {"key": "backup_cell", "name": "备用电源", "type": "device", "rarity": "key_item", "value": 0, "stackable": False, "description": "只能给一套系统续命。", "effects": {}}, {"key": "witness_note", "name": "目击笔记", "type": "evidence", "rarity": "key_item", "value": 0, "stackable": False, "description": "需要与原始日志互相核验。", "effects": {}}, {"key": "exit_key", "name": "出口钥匙", "type": "token", "rarity": "key_item", "value": 0, "stackable": False, "description": "打开容易，代价不会消失。", "effects": {}}, {"key": "voice_recorder", "name": "录音设备", "type": "device", "rarity": "common", "value": 0, "stackable": False, "description": "记录可以被剪辑，也可以被还原。", "effects": {}}, {"key": "seal", "name": "核验封签", "type": "token", "rarity": "key_item", "value": 0, "stackable": False, "description": "证明材料从何而来。", "effects": {}}, {"key": "first_aid", "name": "应急包", "type": "device", "rarity": "common", "value": 0, "stackable": False, "description": "先处理眼前的伤与风险。", "effects": {}}, {"key": "service_key", "name": "后勤钥匙", "type": "token", "rarity": "common", "value": 0, "stackable": False, "description": "通往不在正式导览图上的地方。", "effects": {}}, {"key": "public_notice", "name": "公开通知", "type": "document", "rarity": "common", "value": 0, "stackable": False, "description": "谁能看见、什么时候看见同样重要。", "effects": {}}]})
    dump(root, "skills.yaml", {"skills": [{"key": "investigation", "name": "核验", "category": "professional", "description": "把记录、时间和现场痕迹放到同一条线上。", "max_level": 5}, {"key": "negotiation", "name": "限时交涉", "category": "social", "description": "说明条件、代价和退出方式。", "max_level": 5}, {"key": "survival", "name": "现场应变", "category": "field", "description": "先分清哪件事会立刻伤人。", "max_level": 5}, {"key": "records", "name": "档案复原", "category": "professional", "description": "从缺页、版本与装订痕迹中找到被抹去的部分。", "max_level": 5}], "templates": {}})
    dump(root, "facts.yaml", make_facts(spec))
    dump(root, "plot_threads.yaml", make_threads(spec))
    dump(root, "event_templates.yaml", {"event_types": EVENT_TYPES, "offline_templates": [{"key": "systems_keep_moving", "lod": [1, 2], "weight": 20, "scope": "information", "requires": {"has_public_facts": True}, "effects": {"spread_information": True}, "narrative_hint": "场外系统不会为了任何人暂停。"}, {"key": "people_change_positions", "lod": [1, 2], "weight": 20, "scope": "character", "requires": {"character_type": ["MAJOR_NPC"]}, "effects": {"move_along_schedule": True}, "narrative_hint": "有人先动了，留下可追查的痕迹。"}]})
    dump(root, "narrative_templates.yaml", {"npc_goal_action": "{name}没有等下一轮提问，先去处理{goal}。", "knowledge_hedges": {"UNKNOWN": "{name}没有这条信息。", "SUSPECTED": "{name}有怀疑，但拿不出完整证据。", "KNOWN": "{name}能说明来源与时间。"}, "labels": {"health": "状态", "power": "线索", "location": "地点", "inventory": "材料", "skills": "专长", "relationships": "关系", "quests": "目标", "threads": "局势"}, "action": {"MOVE": "你赶到{location}，倒计时没有因换场而停下。", "TALK": "你把问题摆到{target}面前，对方必须给出回应。", "ASK": "你追问{target}，得到一条能继续核验的信息。", "OBSERVE": "你核对现场，发现一处会改变下一步的细节。", "SEARCH": "你查找材料，把孤立线索接进证据链。", "USE_ITEM": "你出示手中的材料，现场口径立刻变了。", "USE_SKILL": "你用专业能力拆开了对方想混过去的部分。", "CUSTOM": "你的行动迫使局面给出具体结果。", "DEFAULT": "事情向前推进，也留下能追查的后果。"}})
    dump(root, "declarative_rules.yaml", {"rules": [{"key": "work_builds_clues", "trigger": "after_action", "condition": {"op": "in", "args": [{"op": "get", "args": ["action.action_type"]}, ["OBSERVE", "SEARCH", "USE_SKILL"]]}, "effects": [{"op": "adjust_player_resource", "field": "clue", "value": 4}, {"op": "adjust_player_resource", "field": "danger", "value": 2}]}, {"key": "talk_builds_resolve", "trigger": "after_action", "condition": {"op": "in", "args": [{"op": "get", "args": ["action.action_type"]}, ["TALK", "ASK", "CONVERSATION"]]}, "effects": [{"op": "adjust_player_resource", "field": "resolve", "value": 2}]}, {"key": "rest_reduces_danger", "trigger": "after_action", "condition": {"op": "in", "args": [{"op": "get", "args": ["action.action_type"]}, ["REST", "WAIT"]]}, "effects": [{"op": "adjust_player_resource", "field": "danger", "value": -6}]}]})


if __name__ == "__main__":
    for spec in SPECS:
        build(spec)
        print(f"created {spec['key']}")
