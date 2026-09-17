import math

import pytest
import torch
from torch import nn

from src.models.ewc import EWC


def _model():
    torch.manual_seed(0)
    return nn.Linear(2, 1, bias=False)


def test_no_penalty_before_first_consolidation():
    """TRAP 1: nothing to anchor to while learning the first task."""
    m = _model()
    ewc = EWC(m, lam=1e6)
    assert not ewc.active
    assert ewc.penalty().item() == 0.0


def test_penalty_matches_closed_form():
    m = _model()
    ewc = EWC(m, lam=4.0, normalize="none")
    ewc.fisher = {"weight": torch.tensor([[2.0, 0.5]])}
    ewc.frozen = {"weight": torch.tensor([[1.0, -1.0]])}
    ewc.n_consolidations = 1
    with torch.no_grad():
        m.weight.copy_(torch.tensor([[3.0, 1.0]]))
    # 0.5 * lam * sum F (θ-θ*)^2 = 0.5*4*(2*4 + 0.5*4) = 20
    assert math.isclose(ewc.penalty().item(), 20.0, rel_tol=1e-6)
    # gradient = lam * F * (θ-θ*)
    ewc.penalty().backward()
    assert torch.allclose(m.weight.grad, torch.tensor([[16.0, 4.0]]))


def test_fisher_is_mean_squared_raw_gradient():
    m = _model()
    with torch.no_grad():
        m.weight.copy_(torch.tensor([[1.0, 2.0]]))
    ewc = EWC(m, lam=1.0, normalize="none")
    batches = [torch.tensor([[1.0, 0.0]]), torch.tensor([[0.0, 3.0]])]
    loss_fn = lambda model, x: model(x).sum()  # d/dw = x
    info = ewc.consolidate(batches, loss_fn)
    # mean of squared grads: [(1+0)/2, (0+9)/2]
    assert torch.allclose(ewc.fisher["weight"], torch.tensor([[0.5, 4.5]]))
    assert torch.equal(ewc.frozen["weight"], torch.tensor([[1.0, 2.0]]))
    assert info["consolidation"] == 1


def test_fisher_ignores_penalty_gradient():
    """TRAP 2: consolidating twice at the same point with a huge λ must give the
    same importance as the raw task loss, not an inflated one."""
    m = _model()
    ewc = EWC(m, lam=1e6, normalize="none")
    batches = [torch.tensor([[1.0, 1.0]])]
    loss_fn = lambda model, x: model(x).sum()
    ewc.consolidate(batches, loss_fn)
    with torch.no_grad():
        m.weight.add_(5.0)  # far from anchor -> penalty gradient would be enormous
    f2 = ewc.estimate_fisher(batches, loss_fn)
    assert torch.allclose(f2["weight"], torch.tensor([[1.0, 1.0]]))


def test_online_accumulation_and_normalisation():
    m = _model()
    ewc = EWC(m, lam=1.0, gamma=0.5, normalize="max")
    loss_fn = lambda model, x: model(x).sum()
    ewc.consolidate([torch.tensor([[2.0, 1.0]])], loss_fn)
    assert torch.allclose(ewc.fisher["weight"], torch.tensor([[1.0, 0.25]]))
    ewc.consolidate([torch.tensor([[1.0, 2.0]])], loss_fn)
    # 0.5 * old + new(normalised)
    assert torch.allclose(ewc.fisher["weight"], torch.tensor([[0.5 + 0.25, 0.125 + 1.0]]))


def test_stability_warning():
    """TRAP 3: lr*lambda*max(F) above threshold must warn."""
    m = _model()
    ewc = EWC(m, lam=1e4, normalize="max", stability_warn=1.0)
    with pytest.warns(UserWarning, match="TRAP 3"):
        ewc.consolidate([torch.tensor([[1.0, 1.0]])], lambda model, x: model(x).sum(), lr=1e-3)
    assert ewc.stability_ratio(1e-3) == pytest.approx(10.0)


def test_penalty_pulls_back_towards_anchor():
    m = _model()
    ewc = EWC(m, lam=10.0)
    ewc.consolidate([torch.tensor([[1.0, 1.0]])], lambda model, x: model(x).sum())
    anchor = m.weight.detach().clone()
    with torch.no_grad():
        m.weight.add_(1.0)
    opt = torch.optim.SGD(m.parameters(), lr=0.01)
    for _ in range(200):
        opt.zero_grad()
        ewc.penalty().backward()
        opt.step()
    assert torch.allclose(m.weight, anchor, atol=1e-3)
