const STYLE_DEFS = [
  { name: "流行", color: "#13b981", desc: "旋律清晰、情绪表达直接的主流流行音乐。", tags: ["抒情", "青春", "回忆", "情歌", "治愈"] },
  { name: "说唱 / Hip-Hop", color: "#2f80ed", desc: "强调节奏、Flow 与态度表达的城市音乐风格。", tags: ["Flow", "街头", "态度", "现实", "Battle"] },
  { name: "电子 / Dance", color: "#31c6c1", desc: "由电子合成器和节拍驱动的舞曲或实验流行。", tags: ["合成器", "节拍", "舞曲", "未来感", "律动"] },
  { name: "国风 / 古风", color: "#a98cf5", desc: "融合传统文化意象、古典旋律与现代流行编曲。", tags: ["古风", "戏腔", "国潮", "江湖", "山河"] },
  { name: "OST / 影视音乐", color: "#6d8fb5", desc: "与影视、综艺、剧集传播绑定的歌曲类型。", tags: ["剧情", "片尾", "共鸣", "影视", "角色"] },
  { name: "R&B / Soul", color: "#f45f83", desc: "重视律动、转音和细腻情绪的流行分支。", tags: ["律动", "转音", "氛围", "柔和", "夜晚"] },
  { name: "摇滚", color: "#8f63df", desc: "强调吉他、鼓组和现场能量的强表达音乐。", tags: ["吉他", "现场", "力量", "呐喊", "乐队"] },
  { name: "民谣", color: "#f2994a", desc: "以叙事、原声器乐和生活感见长。", tags: ["叙事", "原声", "城市", "故事", "温暖"] },
  { name: "ACG / 二次元", color: "#85c9ff", desc: "围绕动画、游戏、虚拟内容传播的音乐。", tags: ["动画", "游戏", "热血", "角色", "幻想"] },
  { name: "古典", color: "#8fa1b3", desc: "以古典作曲体系、器乐演奏和严肃音乐传统为核心。", tags: ["器乐", "交响", "钢琴", "室内乐", "古典"] },
  { name: "短视频热歌", color: "#ff9f6e", desc: "在短视频平台传播明显、节奏记忆点突出的热门歌曲。", tags: ["短视频", "抖音", "快手", "传播", "记忆点"] },
];

const MAIN_PLATFORMS = [
  { code: "netease", name: "网易云音乐", color: "#00856f" },
  { code: "qq", name: "QQ音乐", color: "#f2994a" },
  { code: "kugou", name: "酷狗音乐", color: "#2f80ed" },
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatNumber(value) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return `${Math.round(number)}`;
}

function formatPercent(value) {
  const number = Number(value || 0);
  return `${Math.round(number)}%`;
}

function platformCode(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("netease") || text.includes("网易") || text.includes("163")) return "netease";
  if (text.includes("qq") || text.includes("tencent")) return "qq";
  if (text.includes("kugou") || text.includes("酷狗")) return "kugou";
  return text || "unknown";
}

function platformName(value) {
  const names = {
    netease: "网易云音乐",
    qq: "QQ音乐",
    kugou: "酷狗音乐",
  };
  const code = platformCode(value);
  return names[code] || value || "未知平台";
}

function normalizePlatformName(value) {
  return platformName(value);
}

function sortPlatformNames(values) {
  const order = { netease: 0, qq: 1, kugou: 2 };
  return Array.from(new Set((values || []).filter(Boolean).map(normalizePlatformName)))
    .sort((a, b) => (order[platformCode(a)] ?? 99) - (order[platformCode(b)] ?? 99));
}

function platformShort(value) {
  const shorts = {
    netease: "网",
    qq: "Q",
    kugou: "酷",
  };
  return shorts[platformCode(value)] || "音";
}

function platformBadge(value) {
  const code = platformCode(value);
  return `<span class="platform-badge ${code}" title="${escapeHtml(platformName(value))}">${escapeHtml(platformShort(value))}</span>`;
}

function platformBadges(values) {
  const order = { netease: 0, qq: 1, kugou: 2 };
  const platforms = Array.from(new Set((values || []).filter(Boolean).map(platformCode)))
    .sort((a, b) => (order[a] ?? 99) - (order[b] ?? 99));
  return platforms.length ? platforms.map(platformBadge).join("") : "";
}

function coverHtml(url, text, className = "cover") {
  const safeText = escapeHtml((text || "音").slice(0, 1));
  if (url) {
    return `<div class="${className}"><img src="${escapeHtml(url)}" alt="${escapeHtml(text || "封面")}" loading="lazy" /></div>`;
  }
  return `<div class="${className}">${safeText}</div>`;
}

function thumbHtml(url, text, className = "item-cover") {
  const safeText = escapeHtml((text || "音").slice(0, 1));
  if (url) {
    return `<span class="${className}"><img src="${escapeHtml(url)}" alt="${escapeHtml(text || "封面")}" loading="lazy" /></span>`;
  }
  return `<span class="${className}">${safeText}</span>`;
}

function normalizeStyleName(styleName) {
  const text = String(styleName || "").trim();
  const lower = text.toLowerCase().replace(/\s+/g, "");
  if (!text) return null;
  if (/^(其他|其他榜|未分类|未识别|unknown|misc|other)$/i.test(text)) return null;
  if (/热歌榜|新歌榜|飙升榜|综合榜|top\s*500|热门歌曲|评论热度榜|平台总榜/i.test(text)) return null;
  if (/说唱|嘻哈|hip-?hop|rap/i.test(text)) return "说唱 / Hip-Hop";
  if (/r&b|soul|节奏布鲁斯/i.test(text)) return "R&B / Soul";
  if (/国风|古风|中国风/.test(text)) return "国风 / 古风";
  if (/ost|影视|原声|剧集|电影/i.test(text)) return "OST / 影视音乐";
  if (/电子|dance|edm|electro|dj|电音/i.test(text)) return "电子 / Dance";
  if (/摇滚|rock/i.test(text)) return "摇滚";
  if (/民谣|folk/i.test(text)) return "民谣";
  if (/acg|二次元|动漫|动画|游戏/i.test(text)) return "ACG / 二次元";
  if (/古典|classical/i.test(text)) return "古典";
  if (/短视频|抖音|快手|tiktok/i.test(text)) return "短视频热歌";
  if (/^(pop|c-pop|cpop|mandopop|mandarinpop|流行|流行榜)$/.test(lower) || /华语流行|国语流行|中文流行|mandarin\s*pop|c-?pop|流行\/pop|pop\/流行/i.test(text)) return "流行";
  return null;
}

function styleDefForName(styleName, index = 0) {
  return STYLE_DEFS.find((style) => style.name === styleName) || STYLE_DEFS[index % STYLE_DEFS.length];
}

function buttonArrow(text) {
  return `${escapeHtml(text)} →`;
}

function tagForSong(song) {
  const joined = `${song.song_name || ""} ${song.album_name || ""} ${song.artist_name || ""}`.toLowerCase();
  if (/rap|hip|说唱|rapper|flow/i.test(joined)) return styleDefForName("说唱 / Hip-Hop");
  if (/r&b|soul|blue|jazz/i.test(joined)) return styleDefForName("R&B / Soul");
  if (/国风|古风|山河|江湖|戏腔|梦/.test(joined)) return styleDefForName("国风 / 古风");
  if (/ost|影视|剧|theme|片尾|电影|国乐/i.test(joined)) return styleDefForName("OST / 影视音乐");
  if (/dj|电音|电子|dance|edm|remix|club/i.test(joined)) return styleDefForName("电子 / Dance");
  if (/rock|摇滚|乐队|guitar/i.test(joined)) return styleDefForName("摇滚");
  if (/民谣|木吉他|远方|故乡|城市/i.test(joined)) return styleDefForName("民谣");
  if (/acg|动漫|游戏|二次元|初音/i.test(joined)) return styleDefForName("ACG / 二次元");
  if (/古典|classical|钢琴|交响/i.test(joined)) return styleDefForName("古典");
  if (/短视频|抖音|快手|tiktok/i.test(joined)) return styleDefForName("短视频热歌");
  return styleDefForName("流行");
}

function heatValue(item) {
  return Number(
    item?.adjusted_heat
    || item?.adjustedHeat
    || item?.heat_score
    || item?.avg_heat_score
    || item?.new_song_score
    || item?.interaction_heat_score
    || item?.artist_heat_score
    || item?.total_score
    || 0
  );
}

function confidenceFromCoverageCount(count) {
  if (count >= 3) return "高";
  if (count === 2) return "中";
  if (count === 1) return "低";
  return "";
}

function songArtistTarget(item) {
  return item?.primary_artist_name || item?.artist_name || item?.display_artist_name || "";
}

function sourcePlatforms(item) {
  const directValues = item?.source_platform_names || item?.platform_names || item?.source_platforms;
  if (Array.isArray(directValues) && directValues.length) return sortPlatformNames(directValues);

  const platformRows = Array.isArray(item?.platforms) ? item.platforms : [];
  const platformNames = platformRows
    .map((row) => (typeof row === "string" ? row : row?.platform_name || row?.platform || row?.name))
    .filter(Boolean);
  return platformNames.length ? sortPlatformNames(platformNames) : [];
}

function setUpdateTime(value) {
  const node = document.querySelector("#updateTime");
  if (node) node.textContent = `更新时间：${value || "-"}`;
}

function setPageMeta(title, eyebrow, subtitle) {
  const titleNode = document.querySelector("#pageTitle");
  const eyebrowNode = document.querySelector("#pageEyebrow");
  const subtitleNode = document.querySelector("#pageSubtitle");
  if (titleNode) titleNode.textContent = title || "";
  if (eyebrowNode) eyebrowNode.textContent = eyebrow || "";
  if (subtitleNode) subtitleNode.textContent = subtitle || "";
}

export {
  MAIN_PLATFORMS,
  STYLE_DEFS,
  buttonArrow,
  coverHtml,
  escapeHtml,
  formatNumber,
  formatPercent,
  confidenceFromCoverageCount,
  heatValue,
  normalizePlatformName,
  normalizeStyleName,
  platformBadge,
  platformBadges,
  platformCode,
  platformName,
  setPageMeta,
  setUpdateTime,
  songArtistTarget,
  sourcePlatforms,
  sortPlatformNames,
  styleDefForName,
  tagForSong,
  thumbHtml,
};
