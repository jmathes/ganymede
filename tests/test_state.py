from ganymede.state import Attempt, Run, Slice, SliceStatus


def test_roundtrip_and_atomic_save(tmp_path):
    run = Run(run_id="r1", paper_path="p.md", slices=[Slice(id="a", title="A", goal="g")])
    run.slices[0].attempts.append(Attempt(prompt="hi"))
    run.save(tmp_path)
    assert not (tmp_path / "r1" / "state.json.tmp").exists()
    back = Run.load(tmp_path, "r1")
    assert back.slices[0].attempts[0].prompt == "hi"
    assert back.status == "planning"


def test_next_slice_respects_dependencies():
    run = Run(run_id="r", paper_path="p", slices=[
        Slice(id="a", title="", goal=""),
        Slice(id="b", title="", goal="", depends_on=["a"]),
    ])
    assert run.next_slice().id == "a"
    run.slices[0].status = SliceStatus.BLOCKED
    assert run.next_slice() is None
    run.slices[0].status = SliceStatus.ACCEPTED
    assert run.next_slice().id == "b"
    run.slices[1].status = SliceStatus.ACCEPTED
    assert run.next_slice() is None and run.all_accepted()
