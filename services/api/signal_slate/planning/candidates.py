"""Constraint-filtered candidate enumeration with no simulator truth access.

A recommendation is a hypothesis, not proof. Available channels and antennas are
configuration options, never labels for a guaranteed repair. Fresh evidence is
required after every intervention, including a coverage-only backup route.
"""

from signal_slate.domain.models import (
    CandidateAction,
    CandidatePlan,
    Constraint,
    Finding,
    RunConfig,
    ShotContext,
    actions_hash,
    canonical_hash,
)


def _validate_action(action: CandidateAction, context: ShotContext) -> None:
    if action.mic_id not in context.mic_ids:
        raise ValueError("Recommendation targets an unknown microphone")
    parameters = action.parameters
    if action.action_type == "CHANNEL_SWITCH":
        if (
            set(parameters) != {"channel"}
            or type(parameters["channel"]) is not int
            or parameters["channel"] not in context.available_channels.get(action.mic_id, [])
        ):
            raise ValueError("Recommendation contains an unavailable channel")
    elif action.action_type == "ANTENNA_SWITCH":
        if (
            set(parameters) != {"antenna"}
            or parameters["antenna"] not in context.available_antennas
        ):
            raise ValueError("Recommendation contains an unavailable antenna")
    elif action.action_type == "BOOM_COVERAGE":
        if set(parameters) != {"source_mic"} or parameters[
            "source_mic"
        ] not in context.available_backup_sources.get(action.mic_id, []):
            raise ValueError("Recommendation contains an unavailable backup source")
    elif parameters:
        raise ValueError("No-action recommendation must not contain parameters")


def _allowed(action: CandidateAction, constraints: list[Constraint]) -> bool:
    for c in constraints:
        if c.kind == "ANTENNA_LOCK" and action.action_type == "ANTENNA_SWITCH":
            # Antenna selection is shared, so a lock applies to the entire rig.
            if action.parameters["antenna"] != c.parameters["locked_antenna"]:
                return False
        if c.target_mic not in (None, action.mic_id):
            continue
        if c.kind == "CHANNEL_EXCLUSION" and action.action_type == "CHANNEL_SWITCH":
            if action.parameters["channel"] == c.parameters["excluded_channel"]:
                return False
        if c.kind == "RIG_LOCK" and action.action_type not in ("NO_ACTION", "BOOM_COVERAGE"):
            return False
        if c.kind == "BOOM_EXCLUSION" and action.action_type == "BOOM_COVERAGE":
            return False
    return True


def _changes_configuration(action: CandidateAction, config: RunConfig) -> bool:
    if action.action_type == "CHANNEL_SWITCH":
        return bool(config.channel_assignments.get(action.mic_id) != action.parameters["channel"])
    if action.action_type == "ANTENNA_SWITCH":
        return bool(config.antenna_selection != action.parameters["antenna"])
    if action.action_type == "BOOM_COVERAGE":
        return bool(config.backup_sources.get(action.mic_id) != action.parameters["source_mic"])
    return True  # Explicit no-action control is labeled as such, never a new repair.


def generate_candidate_plans(
    finding: Finding,
    confirmed_constraints: list[Constraint],
    base_config_hash: str,
    context: ShotContext,
    base_config: RunConfig | None = None,
) -> list[CandidatePlan]:
    """Preserve the model's action type and enumerate only constraint-safe options.

    No selected fault family, seed, or unobserved simulation result is accepted.
    When no compatible receiver correction exists, a permitted backup may cover
    dialogue. Its candidate explicitly retains the unresolved receiver problem.
    """
    if finding.status == "INCONCLUSIVE":
        return []
    if finding.status == "HEALTHY" and finding.recommended_action.action_type != "NO_ACTION":
        raise ValueError("A healthy finding must not recommend a corrective intervention")
    config = base_config or RunConfig()
    for c in confirmed_constraints:
        if not c.confirmed or c.kind == "CUSTOM":
            raise ValueError("Candidate planning requires supported, confirmed constraints")
        if c.target_mic is not None and c.target_mic not in context.mic_ids:
            raise ValueError("Constraint targets an unknown microphone")
        if c.kind == "CHANNEL_EXCLUSION" and (
            set(c.parameters) != {"excluded_channel"}
            or type(c.parameters["excluded_channel"]) is not int
        ):
            raise ValueError("Invalid channel exclusion")
        if c.kind == "ANTENNA_LOCK" and (
            set(c.parameters) != {"locked_antenna"}
            or c.parameters["locked_antenna"] not in context.available_antennas
        ):
            raise ValueError("Invalid antenna lock")
        if c.kind in ("RIG_LOCK", "BOOM_EXCLUSION") and c.parameters:
            raise ValueError("This constraint accepts no parameters")
        if c.kind == "RIG_LOCK" and c.target_mic is None:
            raise ValueError("Rig lock requires a target microphone")

    recommendation = finding.recommended_action
    _validate_action(recommendation, context)
    candidates: list[tuple[str, CandidateAction]] = [("plan_a", recommendation)]
    if finding.status != "HEALTHY":
        if recommendation.action_type == "CHANNEL_SWITCH":
            for channel in context.available_channels.get(recommendation.mic_id, []):
                if channel not in (
                    recommendation.parameters["channel"],
                    config.channel_assignments.get(recommendation.mic_id),
                ):
                    candidates.append(
                        (
                            "plan_b",
                            CandidateAction(
                                action_type="CHANNEL_SWITCH",
                                mic_id=recommendation.mic_id,
                                parameters={"channel": channel},
                            ),
                        )
                    )
        elif recommendation.action_type == "ANTENNA_SWITCH":
            for antenna in context.available_antennas:
                if antenna not in (recommendation.parameters["antenna"], config.antenna_selection):
                    candidates.append(
                        (
                            "plan_b",
                            CandidateAction(
                                action_type="ANTENNA_SWITCH",
                                mic_id=recommendation.mic_id,
                                parameters={"antenna": antenna},
                            ),
                        )
                    )

    feasible = [
        (name, action)
        for name, action in candidates
        if _allowed(action, confirmed_constraints) and _changes_configuration(action, config)
    ]
    corrections = [a for _, a in feasible if a.action_type != "NO_ACTION"]
    if finding.status != "HEALTHY" and not corrections:
        for source in context.available_backup_sources.get(recommendation.mic_id, []):
            backup = CandidateAction(
                action_type="BOOM_COVERAGE",
                mic_id=recommendation.mic_id,
                parameters={"source_mic": source},
            )
            if _allowed(backup, confirmed_constraints) and _changes_configuration(backup, config):
                feasible.append(("plan_b", backup))

    constraints_hash = canonical_hash([c.model_dump(mode="json") for c in confirmed_constraints])
    plans: list[CandidatePlan] = []
    seen = set()
    for index, (name, action) in enumerate(feasible):
        action_hash = actions_hash([action])
        if action_hash in seen:
            continue
        seen.add(action_hash)
        if any(plan.plan_id == name for plan in plans):
            name = f"plan_{index + 1}"
        if action.action_type == "BOOM_COVERAGE":
            rationale = (
                f"Route dialogue for {action.mic_id} from {action.parameters['source_mic']} "
                "if fresh evidence confirms backup availability. Dialogue coverage only; "
                "the original receiver fault remains unresolved."
            )
            tradeoffs = ["Different microphone perspective", "Receiver health is not repaired"]
        elif action.action_type == "NO_ACTION":
            rationale = "Keep the configuration unchanged; this is a control, not a repair claim."
            tradeoffs = ["Any observed fault remains until fresh evidence proves otherwise"]
        else:
            rationale = (
                f"Test {action.action_type.lower().replace('_', ' ')} for {action.mic_id} "
                f"using {action.parameters}. This simulated candidate satisfies confirmed "
                "constraints; improvement is unproven until the repeat rehearsal."
            )
            tradeoffs = [
                "Declared simulation option, not real frequency coordination",
                "Fresh comparison required",
            ]
        plans.append(
            CandidatePlan(
                plan_id=name,
                actions=[action],
                action_hash=action_hash,
                constraints_hash=constraints_hash,
                base_config_hash=base_config_hash,
                rationale=rationale,
                tradeoffs=tradeoffs,
            )
        )
    return plans
