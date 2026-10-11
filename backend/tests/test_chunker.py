from app.protocol.chunker import chunk_protocol


def para(n: int) -> str:
    return " ".join(["word"] * n)


MD = "# T\n\n" + "\n\n".join([
    "## 1. Section 1 [SYNTHETIC]\n\n" + para(40),
    "## 2. Section 2\n\n" + para(60),
    "## 3. Section 3 [SYNTHETIC]\n\n" + "\n\n".join(para(100) for _ in range(4)),
    "## 4. Section 4\n\n" + para(200),
])


def test_chunks_respect_max_and_keep_all_text():
    chunks = chunk_protocol(MD)
    assert all(len(c.text.split()) <= 330 for c in chunks)   # 300 body words + heading words
    assert sum(c.text.count("word") for c in chunks) == 700


def test_small_sections_merge_and_flag_synthetic():
    first = chunk_protocol(MD)[0]
    assert "Section 1" in first.section and "Section 2" in first.section
    assert first.is_synthetic
