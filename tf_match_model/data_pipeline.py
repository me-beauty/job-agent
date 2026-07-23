#!/usr/bin/env python3
"""
数据管线 — 多源岗位数据 → 清洗 → 特征提取 → PyTorch DataLoader

后端：PyTorch + torchtext (或简单 char/token split)

Claude+DeepSeek 分层：
  L1 DeepSeek → JD 降噪、关键词抽取
  L2 PyTorch → 本地训练 (双塔 BiLSTM)
  L3 Claude   → 训练指标分析
  L4 PyTorch → 推理打分
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent

EXCLUDE_KEYWORDS = [
    "销售", "客服", "客户经理", "商务拓展", "BD经理",
    "市场推广", "电话销售", "催收", "保险", "房产",
    "外卖", "配送", "司机", "保安", "保洁",
]

RESUME_FEATURE_KW = [
    "Python", "SQL", "数据分析", "机器学习", "Pandas", "NumPy",
    "Spark", "Hadoop", "TensorFlow", "PyTorch", "Scikit-learn",
    "Tableau", "PowerBI", "数据可视化", "Excel", "统计",
    "深度学习", "NLP", "计算机视觉", "数学建模",
]

# 字符集
VALID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz0123456789 "
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "啊阿埃挨哎哀癌矮艾碍爱隘氨安俺按暗岸胺案肮昂盎凹敖熬翱袄傲奥懊澳芭捌扒叭吧笆八疤巴拔跋靶把耙坝霸罢爸白柏百摆佰败拜稗斑班搬扳般颁板版扮拌伴瓣半办绊邦帮梆榜膀绑棒磅蚌镑傍谤苞胞包褒剥薄雹保堡饱宝抱报暴豹鲍爆杯碑悲卑北辈背贝钡倍狈备惫焙被奔苯本笨崩绷甭泵蹦迸逼鼻比鄙笔彼碧蓖蔽毕毙毖币庇痹闭敝弊必辟壁臂避陛鞭边编贬扁便变卞辨辩辫遍标彪膘表鳖别瘪彬斌濒滨宾摈兵冰柄丙秉饼炳病并玻菠播拨钵波博勃搏铂箔伯帛舶脖膊渤泊驳捕卜哺补埠不布步簿部怖擦猜裁材才财睬踩采彩菜蔡餐参蚕残惭惨灿苍舱仓沧藏操糙槽曹草厕策侧册测层蹭插叉茬茶查碴搽察岔差诧拆柴豺搀掺蝉馋谗缠铲产阐颤昌猖场尝常长偿肠厂敞畅唱倡超抄钞朝嘲潮巢吵炒车扯撤掣彻澈郴臣辰尘晨忱沉陈衬趁撑称城橙成呈乘程惩澄诚承逞骋秤吃痴持匙池迟弛驰耻齿侈尺赤翅斥炽充冲虫崇宠抽酬畴踌稠愁筹仇绸瞅丑臭初出橱厨躇锄雏滁除楚础储矗搐触处揣川穿椽传船喘串疮窗幢床闯创吹炊捶锤垂春椿醇唇淳纯蠢戳绰疵茨磁雌辞慈瓷词此刺赐次聪葱囱勿从丛凑粗醋簇促蹿篡窜摧崔催脆瘁粹淬翠村存寸磋撮搓措挫错搭达答瘩打大呆歹傣戴带殆代贷袋待逮怠耽担丹单郸掸胆旦氮但惮淡诞弹蛋当挡党荡档刀捣蹈倒岛祷导到稻悼道盗德得的蹬灯登等瞪凳邓堤低滴迪敌笛狄涤翟嫡抵底地蒂第帝弟递缔颠掂滇碘点典靛垫电佃甸店惦奠淀殿碉叼雕凋刁掉吊钓调跌爹碟蝶迭谍叠丁盯叮钉顶鼎锭定订丢东冬董懂动栋侗恫冻洞兜抖斗陡豆逗痘都督毒犊独读堵睹赌杜镀肚度渡妒端短锻段断缎堆兑队对墩吨蹲敦顿囤钝盾遁掇哆多夺垛躲朵跺舵剁惰堕蛾峨鹅俄额讹娥恶厄扼遏鄂饿恩而儿耳尔饵洱二贰发罚筏伐乏阀法珐藩帆番翻樊矾钒烦凡础反返范贩犯饭泛坊芳方肪房防妨仿访纺放菲非啡飞肥匪诽吠肺废沸费芬酚吩氛分纷坟焚汾粉奋份忿愤粪丰封枫蜂峰锋风疯烽逢冯缝讽奉凤佛否夫敷肤孵扶拂辐幅氟符伏俘服浮涪福袱弗甫抚辅俯釜斧脯腑府腐赴副覆赋复傅付阜父腹负富讣附妇缚咐噶嘎该改概钙盖溉干甘杆柑竿肝赶感秆敢赣冈刚钢缸肛纲岗港杠篙皋高膏羔糕搞镐稿告哥歌搁戈鸽胳疙割革葛格蛤阁隔铬个各给根跟耕更庚羹埂耿梗工攻功恭龚供躬公宫弓巩汞拱贡共钩勾沟苟狗垢构购够辜菇咕箍估沽孤姑鼓古蛊骨谷股故顾固雇刮瓜剐寡挂褂乖拐怪棺关官冠观管馆罐惯灌贯光广逛瑰规圭硅归龟闺轨鬼诡癸桂柜跪贵刽辊滚棍锅郭国果裹过哈骸孩海氦亥害骇酣憨邯韩含涵寒函喊罕翰撼捍旱憾悍焊汗汉夯杭航壕嚎豪毫郝好耗号浩呵喝荷菏核禾和何合盒貉阂河涸赫褐鹤贺嘿黑痕很狠恨哼亨横衡恒轰哄烘虹鸿洪宏弘红喉侯猴吼厚候后呼乎忽瑚壶葫胡蝴狐糊湖弧虎唬护互沪户花哗华猾滑画划化话槐徊怀淮坏欢环桓还缓换患唤痪豢焕涣宦幻荒慌黄磺蝗簧皇凰惶煌晃幌恍谎灰挥辉徽恢蛔回毁悔慧卉惠晦贿秽会烩汇讳诲绘荤昏婚魂浑混豁活伙火获或惑霍货祸击圾基机畸稽积肌饥迹激讥鸡姬绩缉吉极棘辑籍集及急疾汲即嫉级挤几脊己蓟技冀季伎祭剂悸济寄寂计记既忌际妓继纪嘉枷夹佳家加荚颊贾甲钾假稼价架驾嫁歼监坚尖笺间煎兼肩艰奸缄茧检柬碱硷拣捡简俭剪减荐槛鉴践贱见键箭件健舰剑饯渐溅涧建僵姜将浆江疆蒋桨奖讲匠酱降蕉椒礁焦胶交郊浇骄娇嚼搅铰矫侥脚狡角饺缴绞剿教酵轿较叫窖揭接皆秸街阶截劫节桔杰捷睫竭洁结解姐戒藉芥界借介疥诫届巾筋斤金今津襟紧锦仅谨进靳晋禁近烬浸尽劲荆兢茎睛晶鲸京惊精粳经井警景颈静境敬镜径痉靖竟竞净炯窘揪究纠玖韭久灸九酒厩救旧臼舅咎就疚鞠拘狙疽居驹菊局咀矩举沮聚拒据巨具距踞锯俱句惧炬剧捐鹃娟倦眷卷绢撅攫抉掘倔爵觉决诀绝均菌钧军君峻俊竣浚郡骏喀咖卡咯开揩楷凯慨刊堪勘坎砍看康慷糠扛抗亢炕考拷烤靠坷苛柯棵磕颗科壳咳可渴克刻客课肯啃垦恳坑吭空孔控抠口扣寇枯哭窟苦酷库裤夸垮挎跨胯块筷侩快宽款匡筐狂框矿眶旷况亏盔岿窥葵奎魁傀馈愧溃坤昆捆困括扩廓阔垃拉喇蜡腊辣啦莱来赖蓝婪栏拦篮阑兰澜谰揽览懒缆烂滥琅榔狼廊郎朗浪捞劳牢老佬姥酪烙涝勒乐雷镭蕾磊累儡垒擂肋类泪棱楞冷厘梨犁黎篱狸离漓理李里鲤礼莉荔吏栗丽厉励砾历利傈例俐痢立粒沥隶力璃哩俩联莲连镰廉怜涟帘敛脸链恋炼练粮凉梁粱良两辆量晾亮谅撩聊僚疗燎寥辽潦了撂镣廖料列裂烈劣猎琳林磷霖临邻鳞淋凛赁吝拎玲菱零龄铃伶羚凌灵陵岭领另令溜琉榴硫馏留刘瘤流柳六龙聋咙笼窿隆垄拢陇楼娄搂篓漏陋芦卢颅庐炉掳卤虏鲁麓碌露路赂鹿潞禄录陆戮驴吕铝侣旅履屡缕虑氯律率滤绿峦挛孪滦卵乱掠略抡轮伦仑沦纶论萝螺罗逻锣箩骡裸落洛骆络妈麻玛码蚂马骂嘛吗埋买麦卖迈脉瞒馒蛮满蔓曼慢漫谩芒茫盲氓忙莽猫茅锚毛矛铆卯茂冒帽貌贸么玫枚梅酶霉煤没眉媒镁每美昧寐妹媚门闷们萌蒙檬盟锰猛梦孟眯醚靡糜迷谜弥米秘觅泌蜜密幂棉眠绵冕免勉缅缅面苗描瞄藐秒渺庙妙蔑灭民抿皿敏悯闽明螟鸣铭名命谬摸摹蘑模膜磨摩魔抹末莫墨默沫漠寞陌谋牟某拇牡亩姆母墓暮幕募慕木目睦牧穆拿哪呐钠那娜纳氖乃奶耐奈南男难囊挠脑恼闹淖呢馁内嫩能妮霓倪泥尼拟你匿腻逆溺蔫拈年碾撵捻念娘酿鸟尿捏聂孽啮镊镍涅您柠狞凝宁拧泞牛扭钮纽脓浓农弄奴努怒女暖虐疟挪懦糯诺哦欧鸥殴藕呕偶沤啪趴爬帕怕琶拍排牌徘湃派攀潘盘磐盼畔判叛乓庞旁耪胖抛咆刨炮袍跑泡呸胚培裴赔陪配佩沛喷盆砰抨烹澎彭蓬棚硼篷膨朋鹏捧碰坯砒霹批披劈琵毗啤脾疲皮匹痞僻屁譬篇偏片骗飘漂瓢票撇瞥拼频贫品聘乒坪苹萍平凭瓶评屏坡泼颇婆破魄迫粕剖扑铺仆莆葡菩蒲埔朴圃普浦谱曝瀑期欺栖戚妻七凄漆柒沏其棋奇歧畦崎脐齐旗祈祁骑起岂乞企启契砌器气迄弃汽泣讫掐恰洽牵扦钎铅千迁签仟谦乾黔钱钳前潜遣浅谴堑嵌欠歉枪呛腔羌墙蔷强抢橇锹敲悄桥瞧乔侨巧鞘撬翘峭俏窍切茄且怯窃钦侵亲秦琴勤芹擒禽寝沁青轻氢倾卿清擎晴氰情顷请庆琼穷秋丘邱球求囚酋泅趋区蛆曲躯屈驱渠取娶龋趣去圈颧权醛泉全痊拳犬券劝缺炔瘸却鹊榷确雀裙群然燃冉染瓤壤攘嚷让饶扰绕惹热壬仁人忍韧任认刃妊纫扔仍日戎茸蓉荣融熔溶容绒冗揉柔肉茹蠕儒孺如辱乳汝入褥软阮蕊瑞锐闰润若弱撒洒萨腮鳃塞赛三叁伞散桑嗓丧搔骚扫嫂瑟色涩森僧莎砂杀刹沙纱傻啥煞筛晒珊苫杉山删煽衫闪陕擅赡膳善汕扇缮墒伤商赏晌上尚裳梢捎稍烧芍勺韶少哨邵绍奢赊蛇舌舍赦慑射涉社设砷申呻伸身深娠绅神沈审婶甚肾慎渗声生甥牲升绳省盛剩胜圣师失狮施湿诗尸虱十石拾时什食蚀实识史矢使屎驶始式示士世柿事拭誓逝势是嗜噬适仕侍释饰氏市恃室视试收手首守寿授售受瘦兽蔬枢梳殊抒输叔舒淑疏书赎孰熟薯暑曙署蜀黍鼠属术述树束戍竖墅庶数漱恕刷耍摔衰甩帅栓拴霜双爽谁水睡税吮瞬顺舜说硕朔烁斯撕嘶思私司丝死肆寺嗣四伺似饲巳松耸怂颂送宋讼诵搜艘擞嗽苏酥俗素速粟僳塑溯宿诉肃酸蒜算虽隋随绥髓碎岁穗遂隧祟孙损笋蓑梭唆缩琐索锁所塌他它她塔獭挞蹋踏胎苔抬台泰酞太态汰坍摊贪瘫滩坛檀痰潭谭谈坦毯袒碳探叹炭汤塘搪堂棠膛唐糖倘躺淌趟烫掏涛滔绦萄桃逃淘陶讨套特藤腾疼誊梯剔踢锑提题蹄啼体替嚏惕涕剃屉天添填田甜恬舔腆挑条迢眺跳贴铁帖厅听烃汀廷停亭庭挺艇通桐酮瞳同铜彤童桶捅筒统痛偷投头透凸秃突图徒途涂屠土吐兔湍团推颓腿蜕褪退吞屯臀拖托脱鸵陀驮驼椭妥拓唾挖哇蛙洼娃瓦袜歪外豌弯湾玩顽丸烷完碗挽晚皖惋宛婉万腕汪王亡枉网往旺望忘妄威巍微危韦违桅围唯惟为潍维苇萎委伟伪尾纬未蔚味畏胃喂魏位渭谓尉慰卫瘟温蚊文闻纹吻稳紊问嗡翁瓮挝蜗涡窝我斡卧握沃巫呜钨乌污诬屋无芜梧吾吴毋武五捂午舞伍侮坞戊雾晤物勿务悟误昔熙析西硒矽晰嘻吸锡牺稀息希悉膝夕惜熄烯溪汐犀檄袭席习媳喜铣洗系隙戏细瞎虾匣霞辖暇峡侠狭下厦夏吓掀锨先仙鲜纤咸贤衔舷闲涎弦嫌显险现献县腺馅羡宪陷限线相厢镶香箱襄湘乡翔祥详想响享项巷橡像向象萧硝霄削哮嚣销消宵淆晓小孝校肖啸笑效楔些歇蝎鞋协携邪斜胁谐写械卸蟹懈泄泻谢屑薪芯锌欣辛新忻心信衅星腥猩惺兴刑型形邢行醒幸杏性姓兄凶胸匈汹雄熊休修羞朽嗅锈秀袖绣墟戌需虚嘘须徐许蓄酗叙旭序畜恤絮婿绪续轩喧宣悬旋玄选癣眩绚靴薛穴学雪血勋熏循旬询寻驯巡殉汛训讯逊迅压押鸦鸭呀丫芽牙蚜崖衙涯雅哑亚讶焉咽阉烟淹盐严研蜒岩延言颜阎炎沿奄掩眼衍演艳堰燕厌砚雁唁彦焰宴谚验殃央鸯秧杨扬佯疡羊洋阳氧仰痒养样漾邀腰妖瑶摇尧遥窑谣姚咬舀药要耀椰噎耶爷野冶也页掖业叶曳腋夜液一壹医揖铱依伊衣颐夷遗移仪胰疑沂宜姨彝椅蚁倚已乙矣以艺抑易邑屹亿役臆逸肄疫亦裔意毅忆义益溢诣议谊译异翼翌绎茵荫因殷音阴姻吟银淫寅饮尹引隐印英樱婴鹰应缨莹萤营荧蝇迎赢盈影颖硬映哟拥佣臃痈庸雍踊蛹咏泳涌永恿勇用幽优悠忧尤由邮铀犹油游酉有友右佑釉诱又幼迂淤于盂榆虞愚舆余俞逾鱼愉渝渔隅予娱雨与屿禹宇语羽玉域芋郁吁遇喻峪御愈欲狱育誉浴寓裕预豫驭鸳渊冤元垣袁原援辕园员圆猿源缘远苑愿怨院曰约越跃钥岳粤月悦阅耘云郧匀陨允运蕴酝晕韵孕匝砸杂栽哉灾宰载再在咱攒暂赞赃脏葬遭糟凿藻枣早澡蚤躁噪造皂灶燥责择则泽贼怎增憎曾赠扎喳渣札轧铡闸眨栅榨咋乍炸诈摘斋宅窄债寨瞻毡詹粘沾盏斩辗崭展蘸栈占战站湛绽樟章彰漳张掌涨杖丈帐账仗胀瘴障招昭找沼赵照罩兆肇召遮折哲蛰辙者锗蔗这浙珍斟真甄砧臻贞针侦枕疹诊震振镇阵蒸挣睁征狰争怔整拯正政帧症郑证芝枝支吱蜘知肢脂汁之织职直植殖执值侄址指止趾只旨纸志挚掷至致置帜峙制智秩稚质炙痔滞治窒中盅忠钟衷终种肿重仲众舟周州洲诌粥轴肘帚咒皱宙昼骤珠株蛛朱猪诸诛逐竹烛煮拄瞩嘱主著柱助蛀贮铸筑住祝注驻抓爪拽专砖转撰赚篆桩庄装妆撞壮状椎锥追赘坠缀谆准捉拙卓桌琢茁酌啄着灼浊兹咨资姿滋淄孜紫仔籽滓子自渍字鬃棕踪宗综总纵邹走奏揍租足卒族祖诅阻组钻纂嘴醉最罪尊遵昨左佐柞做作坐座"
)
MIN_CHAR_IDX = 1   # 0 = padding
char_to_idx = {c: i + MIN_CHAR_IDX for i, c in enumerate(sorted(VALID_CHARS))}
VOCAB_SIZE = len(char_to_idx) + MIN_CHAR_IDX + 1  # +1 for <UNK>
UNK_IDX = len(char_to_idx) + MIN_CHAR_IDX


def text_to_ids(text: str, max_len: int = 512) -> list[int]:
    """字符级编码"""
    ids = [char_to_idx.get(c, UNK_IDX) for c in text[:max_len]]
    return ids


# ============================================================
# DeepSeek 文本预处理（L1）
# ============================================================

def _call_deepseek_preprocess(text: str, task: str = "denoise") -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return _rule_based_preprocess(text, task)
    try:
        from openai import OpenAI
    except ImportError:
        return _rule_based_preprocess(text, task)

    prompts = {
        "denoise": "你是文本清洗助手。去除以下JD中无关内容（HTML、福利废话），只保留岗位职责和任职要求。纯文本，不超300字。\n\n",
        "keywords": "从以下JD提取10-15个核心技能关键词，逗号分隔，不要解释。\n\n",
    }
    prompt = prompts.get(task, "denoise") + text[:2000]
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return _rule_based_preprocess(text, task)


def _rule_based_preprocess(text: str, task: str) -> str:
    if task == "keywords":
        found = [kw for kw in RESUME_FEATURE_KW if kw.lower() in text.lower()]
        return ", ".join(found) if found else text[:200]
    if task == "denoise":
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:500]
    return text


# ============================================================
# JobDataPipeline
# ============================================================

class JobDataPipeline:
    """多源读取 → 清洗 → PyTorch 训练数据"""

    def __init__(self, use_deepseek: bool = True, max_len: int = 512):
        self.rows: list[dict] = []
        self.cleaned: list[dict] = []
        self.use_deepseek = use_deepseek
        self.max_len = max_len

    def load_csv(self, path: str) -> int:
        count = 0
        p = Path(path)
        if not p.exists(): return 0
        with open(p, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                self.rows.append({
                    "source": f"csv:{p.name}",
                    "title": row.get("title") or row.get("position", ""),
                    "company": row.get("company", ""),
                    "description": row.get("description") or row.get("desc", ""),
                    "location": row.get("location", ""),
                    "salary": row.get("salary", ""),
                })
                count += 1
        print(f"   CSV: {count} ({p.name})")
        return count

    def load_markdown(self, path: str) -> int:
        p = Path(path)
        if not p.exists(): return 0
        try:
            sys.path.insert(0, str(ROOT))
            from report_utils import parse_table_rows
            count = 0
            for r in parse_table_rows(p.read_text(encoding="utf-8")):
                self.rows.append({"source": f"md:{p.name}", "title": r.get("position",""),
                                  "company": r.get("company",""), "description": "",
                                  "location": r.get("location",""), "salary": ""})
                count += 1
            print(f"   MD: {count} ({p.name})")
            return count
        except ImportError:
            return self._parse_md_fallback(p)

    def _parse_md_fallback(self, p: Path) -> int:
        count = 0; in_table = False
        for line in p.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line.startswith("|") and "公司" in line: in_table = True; continue
            if line.startswith("|---"): continue
            if in_table and line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 3:
                    self.rows.append({"source": f"md:{p.name}", "title": cells[2], "company": cells[1],
                                      "description": "", "location": cells[3] if len(cells)>3 else "", "salary": ""})
                    count += 1
            elif in_table and not line.startswith("|"): in_table = False
        return count

    def load_jobhunt_config(self) -> int:
        count = 0
        try:
            sys.path.insert(0, str(ROOT))
            from report_utils import JOBHUNT_COMPANIES, COMPANY_NAMES, JOBHUNT_KEYWORDS, JOBHUNT_LOCATIONS
            for ck in JOBHUNT_COMPANIES:
                name = COMPANY_NAMES.get(ck, ck)
                for kw in JOBHUNT_KEYWORDS:
                    for loc in JOBHUNT_LOCATIONS:
                        self.rows.append({"source":"jobhunt", "title":f"{kw}实习生", "company":name,
                                          "description":f"{name} {kw} 实习 {loc}", "location":loc, "salary":""})
                        count += 1
            print(f"   jobhunt: {count}")
        except ImportError:
            pass
        return count

    def load_resume_template(self) -> dict:
        p = ROOT / "resume_template.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def clean_and_filter(self) -> int:
        try:
            sys.path.insert(0, str(ROOT))
            from report_utils import _normalize
        except ImportError:
            def _normalize(t): return t.strip().lower().replace(" ","").replace("　","")

        seen = set(); cleaned = []
        for row in self.rows:
            key = f"{_normalize(row['title'])}|{_normalize(row['company'])}"
            if key in seen: continue
            seen.add(key)
            combined = f"{row['title']} {row.get('description','')}".lower()
            if any(kw in combined for kw in EXCLUDE_KEYWORDS): continue
            desc = row.get("description","")
            if self.use_deepseek and len(desc) > 100:
                row["description_clean"] = _call_deepseek_preprocess(desc, "denoise")
                row["keywords"] = _call_deepseek_preprocess(desc, "keywords")
            else:
                row["description_clean"] = desc
                row["keywords"] = _rule_based_preprocess(desc, "keywords")
            row["text"] = f"{row['title']} {row['company']} {row.get('description_clean', desc)}"
            cleaned.append(row)
        self.cleaned = cleaned
        print(f"   Clean: {len(self.rows)} -> {len(cleaned)}")
        return len(cleaned)

    def build_dataset(self, resume_text: str, val_split: float = 0.2, seed: int = 42) -> dict:
        """构建 PyTorch 训练数据"""
        import torch

        if not self.cleaned:
            self.clean_and_filter()

        resume_kw = set(kw for kw in RESUME_FEATURE_KW if kw.lower() in resume_text.lower())

        r_ids = []
        j_ids = []
        labels = []

        for row in self.cleaned:
            jd = row.get("text", row.get("title",""))
            if not jd.strip(): continue
            r_ids.append(text_to_ids(resume_text, self.max_len))
            j_ids.append(text_to_ids(jd, self.max_len))
            jd_kw = set(k.strip() for k in row.get("keywords","").split(",") if k.strip())
            hits = len(resume_kw & jd_kw)
            score = min(95, max(10, int(hits / max(len(resume_kw), 1) * 80 + 15)))
            labels.append(score)

        if not labels:
            raise ValueError("No training data!")

        n = len(labels)
        idx = np.random.RandomState(seed).permutation(n)
        split = int(n * (1 - val_split))

        def to_tensor(id_list):
            # Pad to max_len
            arr = np.zeros((len(id_list), self.max_len), dtype=np.int64)
            for i, ids in enumerate(id_list):
                L = min(len(ids), self.max_len)
                arr[i, :L] = ids[:L]
            return torch.tensor(arr, dtype=torch.long)

        train_r = to_tensor([r_ids[i] for i in idx[:split]])
        train_j = to_tensor([j_ids[i] for i in idx[:split]])
        train_y = torch.tensor([labels[i] for i in idx[:split]], dtype=torch.float32)

        val_r = to_tensor([r_ids[i] for i in idx[split:]])
        val_j = to_tensor([j_ids[i] for i in idx[split:]])
        val_y = torch.tensor([labels[i] for i in idx[split:]], dtype=torch.float32)

        print(f"   Dataset: train={split}, val={n-split}, vocab={VOCAB_SIZE}")
        return {
            "train": (train_r, train_j, train_y),
            "val": (val_r, val_j, val_y),
            "vocab_size": VOCAB_SIZE,
            "max_len": self.max_len,
        }

    @property
    def summary(self) -> dict:
        return {"raw": len(self.rows), "cleaned": len(self.cleaned)}
