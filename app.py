from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from research_mapper.analysis import candidates, concepts, export_json, graph_dot, grouped_claims
from research_mapper.extract import extract_paper
from research_mapper.sources import ArxivLoadError, fetch_arxiv_ids, read_pdf, search_arxiv


st.set_page_config(page_title="研际 · Research Horizon", page_icon="🧭", layout="wide")

for key, default in {"papers": [], "claims": [], "mappings": {}, "warnings": [], "scope": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def set_corpus(papers: list[dict], scope: str, claims: list[dict] | None = None) -> None:
    st.session_state.papers = list({p["id"]: p for p in papers}.values())
    st.session_state.claims = claims or []
    st.session_state.mappings = {}
    st.session_state.warnings = []
    st.session_state.scope = scope


def show_claim(claim: dict) -> None:
    paper = next((p for p in st.session_state.papers if p["id"] == claim["paper_id"]), None)
    if paper is None:
        return
    label = paper["title"]
    if paper["url"]:
        st.markdown(f"[{label}]({paper['url']}) · {paper['source']}")
    else:
        st.write(f"**{label}** · {paper['source']}")
    st.caption(f"问题：{claim['problem']} ｜ 方法：{claim['method']} ｜ 数据集：{claim.get('dataset') or '未提取'}")
    st.info(claim["quote"])


st.title("🧭 研际 · Research Horizon")
st.caption("连接已有知识，发现下一步可能。")
st.caption("从论文中连接问题、方法与数据集，用原文证据探索值得研究的新方向。")

with st.sidebar:
    st.header("1 · 载入论文")
    source = st.radio("输入方式", ["示例数据", "arXiv 搜索", "arXiv ID", "上传 PDF"])
    if source == "arXiv 搜索":
        query = st.text_input("英文研究主题", placeholder="clinical event extraction")
        limit = st.slider("最多返回论文数", 3, 30, 12)
    elif source == "arXiv ID":
        ids = st.text_area("arXiv ID，以逗号或空格分隔", placeholder="2301.00001, 2301.00002")
    elif source == "上传 PDF":
        files = st.file_uploader("论文 PDF", type="pdf", accept_multiple_files=True)
    if source in {"arXiv 搜索", "arXiv ID"}:
        st.caption("相同查询缓存 1 小时；遇到临时限流会等待后有限重试，请勿连续点击。")
    if st.button("载入论文", width="stretch", type="primary"):
        try:
            if source == "示例数据":
                example = json.loads((Path(__file__).parent / "sample_papers.json").read_text(encoding="utf-8"))
                set_corpus(example["papers"], "合成演示数据：4 篇虚构论文；不能用于实际研究结论。", example["claims"])
            elif source == "arXiv 搜索":
                with st.spinner("正在获取 arXiv 论文；如遇限流，会等待后重试…"):
                    papers = search_arxiv(query, limit)
                set_corpus(papers, f"arXiv 搜索：{query!r}；前 {len(papers)} 篇结果；仅题名与摘要。")
            elif source == "arXiv ID":
                with st.spinner("正在获取 arXiv 论文；如遇限流，会等待后重试…"):
                    papers = fetch_arxiv_ids(ids)
                set_corpus(papers, f"指定 arXiv ID：{len(papers)} 篇；仅题名与摘要。")
            else:
                if not files:
                    raise ValueError("请先上传至少一篇 PDF。")
                papers = [read_pdf(file.name, file.getvalue()) for file in files]
                set_corpus(papers, f"上传 PDF：{len(papers)} 篇；每篇最多前 20 页 / 18,000 字。")
            if not st.session_state.papers:
                st.warning("没有找到可用论文，请调整输入。")
        except ArxivLoadError as exc:
            st.warning(str(exc))
            if st.session_state.papers:
                st.caption("本次载入未成功，当前已载入的论文仍然保留。")
        except (ValueError, requests.RequestException, OSError, json.JSONDecodeError) as exc:
            st.error(f"载入失败：{exc}")

    st.divider()
    st.header("2 · AI 抽取")
    model = st.text_input("Ollama 模型", value="qwen2.5:7b")
    st.caption("需在本机启动 Ollama。每个组合必须附有可在原文中找到的引文。")
    try:
        ollama_response = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
        ollama_response.raise_for_status()
        installed_models = {item.get("name", "") for item in ollama_response.json().get("models", [])}
        model_ready = model in installed_models
        if model_ready:
            st.success(f"本地模型已就绪：{model}")
        else:
            st.warning(f"Ollama 已启动，但尚未找到模型 {model}。请先下载该模型。")
    except (requests.RequestException, ValueError):
        model_ready = False
        st.warning("未连接到本机 Ollama。请先在 PyCharm 运行 setup_local.py，再运行 launch.py；也可先载入示例预览。")
    if st.button("抽取证据", width="stretch", disabled=not st.session_state.papers or not model_ready):
        claims, warnings = [], []
        progress = st.progress(0)
        for index, paper in enumerate(st.session_state.papers):
            try:
                found, notes = extract_paper(paper, model)
                claims.extend(found)
                warnings.extend(f"{paper['title']}：{note}" for note in notes)
            except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"{paper['title']}：抽取失败：{exc}")
            progress.progress((index + 1) / len(st.session_state.papers))
        st.session_state.claims = claims
        st.session_state.warnings = warnings
        st.session_state.mappings = {}
        if not claims:
            st.error("未得到有效证据。请确认 Ollama 已启动、模型已下载，或换一批论文。")

if not st.session_state.papers:
    st.info("从左侧载入示例数据，即可预览完整流程。要分析实际论文，请选择 arXiv 或上传 PDF。")
    st.stop()

st.subheader("当前语料")
st.warning(st.session_state.scope)
papers = st.session_state.papers
claims = st.session_state.claims
c1, c2, c3 = st.columns(3)
c1.metric("论文", len(papers))
c2.metric("带原文证据的组合", len(claims))
c3.metric("候选空格", len(candidates(grouped_claims(claims, st.session_state.mappings))))

with st.expander("查看论文与抽取状态", expanded=not claims):
    for paper in papers:
        st.write(f"**{paper['title']}** · {paper['source']} · {paper['id']}")
        if paper["url"]:
            st.markdown(f"[查看原论文]({paper['url']})")
    for note in st.session_state.warnings:
        st.warning(note)

if not claims:
    st.info("请在左侧点击“抽取证据”，或载入示例数据。")
    st.stop()

graph_tab, matrix_tab, gap_tab, edit_tab, export_tab = st.tabs(
    ["知识图谱", "问题 × 方法矩阵", "候选机会", "概念归一", "导出"]
)

with graph_tab:
    st.markdown("**红色：研究问题　蓝色：方法　绿色：数据集**")
    st.graphviz_chart(graph_dot(claims, st.session_state.mappings))
    st.caption("连线来自同一篇论文中经原文验证的抽取组合。方法到数据集的连线表示该组合提及该数据集。")

groups = grouped_claims(claims, st.session_state.mappings)
problems = sorted({p for p, _ in groups}, key=str.casefold)
methods = sorted({m for _, m in groups}, key=str.casefold)

with matrix_tab:
    st.write("单元格数字表示支持该问题与方法组合的论文篇数；0 表示当前语料未发现直接证据。")
    rows = []
    for problem in problems:
        row = {"研究问题": problem}
        for method in methods:
            row[method] = len({item["paper_id"] for item in groups.get((problem, method), [])})
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    left, right = st.columns(2)
    selected_problem = left.selectbox("查看问题", problems)
    selected_method = right.selectbox("查看方法", methods)
    matched = groups.get((selected_problem, selected_method), [])
    if matched:
        st.success(f"当前语料中有 {len({item['paper_id'] for item in matched})} 篇论文支持此组合。")
        for claim in matched:
            show_claim(claim)
    else:
        st.warning("当前语料未发现直接证据。需要扩展检索与人工复核。")

with gap_tab:
    st.caption("候选排序依据相邻格子的论文数。空格不等于全领域无人研究，也不代表技术可行。")
    gaps = candidates(groups)
    if not gaps:
        st.info("当前没有同时具备两侧相邻证据的空格。可以增加论文或调整概念归一。")
    for index, gap in enumerate(gaps[:20], start=1):
        with st.expander(f"{index}. {gap['problem']} × {gap['method']}  ·  相邻证据分 {gap['score']}"):
            st.write(f"**同一问题已有的其他方法**（{len(gap['problem_neighbors'])} 条证据）")
            for claim in gap["problem_neighbors"][:3]:
                show_claim(claim)
            st.write(f"**同一方法用于的其他问题**（{len(gap['method_neighbors'])} 条证据）")
            for claim in gap["method_neighbors"][:3]:
                show_claim(claim)
            st.caption("下一步：补查同义关键词、其他数据库和论文全文，再判断该组合是否值得研究。")

with edit_tab:
    st.write("若多篇论文对同一概念使用不同名称，可把它们改为相同的标准名。修改后图谱和矩阵会重新计算。")
    labels = concepts(claims)
    table = pd.DataFrame([{"原始概念": label, "标准名称": st.session_state.mappings.get(label, label)} for label in labels])
    editor_id = hashlib.sha1(json.dumps({"labels": labels, "mappings": st.session_state.mappings}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        disabled=["原始概念"],
        num_rows="fixed",
        key=f"concept_editor_{editor_id}",
    )
    if st.button("应用概念映射"):
        st.session_state.mappings = {
            str(row["原始概念"]): str(row["标准名称"]).strip()
            for _, row in edited.iterrows()
            if str(row["标准名称"]).strip() and row["原始概念"] != row["标准名称"]
        }
        st.rerun()

with export_tab:
    st.write("导出论文、抽取结果和概念映射，便于人工复核与后续分析。")
    st.download_button(
        "下载 JSON",
        data=export_json(papers, claims, st.session_state.mappings),
        file_name="research_horizon.json",
        mime="application/json",
    )
