use graphdlc_core::{self as core, consts::*, state::get_state};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    io::{self, Read},
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NodeConfig {
    x: i32,
    y: i32,
    arrow_type: u8,
    node_type: u8,
    links: Vec<u32>,
    detectors: Vec<u32>,
    detected: i32,
    blocked: i32,
    cycle_idx: i32,
    cycle_offset: u32,
    head_type: u8,
    entry: bool,
    additional: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CycleConfig {
    index: u32,
    length: u32,
    nodes: Vec<u32>,
    heads: Vec<u32>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Port {
    at: [i32; 2],
    values: Vec<Option<u8>>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scenario {
    ticks: usize,
    #[serde(default)]
    limits: Limits,
    #[serde(default)]
    hold_ticks: Option<usize>,
    #[serde(default)]
    frame_ticks: Option<Vec<usize>>,
    #[serde(default)]
    seed: Option<u64>,
    #[serde(default)]
    inputs: Vec<Port>,
    expect: Vec<Port>,
    #[serde(default)]
    observe: Vec<[i32; 2]>,
}
#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Limits {
    nodes: usize,
    ticks: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self { nodes: 1_000_000, ticks: 1_000_000 }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    nodes: Vec<NodeConfig>,
    cycles: Vec<CycleConfig>,
    test: Scenario,
}

fn find_port(
    nodes: &[NodeConfig],
    port: &Port,
    expected_type: u8,
    samples: usize,
) -> Result<usize, String> {
    if port.values.len() != samples
        || port.values.iter().any(|v| v.is_some_and(|v| v > 1))
        || (expected_type == 22 && port.values.iter().any(Option::is_none))
        || (expected_type == 23 && port.values.iter().all(Option::is_none))
    {
        return Err(format!(
            "Порт {:?}: нужны {samples} значений 0/1; null разрешён только для непроверяемого выхода, хотя бы один образец должен проверяться",
            port.at
        ));
    }
    let index = nodes
        .iter()
        .position(|n| [n.x, n.y] == port.at)
        .ok_or_else(|| format!("Порт {:?} отсутствует", port.at))?;
    if nodes[index].arrow_type != expected_type {
        return Err(format!("Порт {:?}: требуется тип {expected_type}", port.at));
    }
    Ok(index)
}

fn run(request: Request) -> Result<Value, String> {
    let Request {
        nodes,
        cycles,
        test,
    } = request;
    if test.limits.nodes == 0 || test.limits.nodes > i32::MAX as usize || test.limits.ticks == 0 {
        return Err("Лимиты должны быть положительными; nodes не больше 2147483647".into());
    }
    if test.ticks == 0 || test.ticks > test.limits.ticks {
        return Err(format!("Количество тактов должно быть от 1 до {}", test.limits.ticks));
    }
    let hold = test.hold_ticks.unwrap_or(1);
    if hold == 0 || test.ticks % hold != 0 {
        return Err("hold_ticks должен быть положительным делителем количества тактов".into());
    }
    let samples = if let Some(frames) = &test.frame_ticks {
        if test.hold_ticks.is_some()
            || frames.is_empty()
            || frames.iter().any(|&v| v == 0 || v > test.ticks)
            || frames.iter().try_fold(0usize, |a, &b| a.checked_add(b)) != Some(test.ticks)
        {
            return Err("frame_ticks: положительные длительности должны суммироваться в ticks; hold_ticks одновременно не допускается".into());
        }
        frames.len()
    } else {
        test.ticks / hold
    };
    if test.expect.is_empty() && test.observe.is_empty() {
        return Err("Нужен хотя бы один проверяемый приёмник".into());
    }
    if nodes.len() > test.limits.nodes {
        return Err("Слишком много узлов".into());
    }
    let mut inputs = Vec::new();
    let mut outputs = Vec::new();
    let mut used = HashSet::new();
    for port in &test.inputs {
        let index = find_port(&nodes, port, 22, samples)?;
        if !used.insert(index) {
            return Err("Повторный входной порт".into());
        }
        if nodes[index].cycle_idx >= 0 {
            return Err("Входной порт был включён в оптимизированное кольцо".into());
        }
        inputs.push(index);
    }
    used.clear();
    for port in &test.expect {
        let index = find_port(&nodes, port, 23, samples)?;
        if !used.insert(index) {
            return Err("Повторный выходной порт".into());
        }
        outputs.push(index);
    }
    let mut observed = Vec::new();
    used.clear();
    for at in &test.observe {
        let index = nodes.iter().position(|n| [n.x, n.y] == *at)
            .ok_or_else(|| format!("Наблюдаемая клетка {at:?} отсутствует"))?;
        if !used.insert(index) {
            return Err("Повторная наблюдаемая клетка".into());
        }
        observed.push(index);
    }
    let len = nodes.len() as u32;
    for node in &nodes {
        if node.links.len() > 4
            || node.detectors.len() > 4
            || node.links.iter().chain(&node.detectors).any(|&n| n >= len)
            || node.detected < -1
            || node.blocked < -1
            || node.detected >= len as i32
            || node.blocked >= len as i32
            || node.node_type > NODE_TYPE_DIRECTIONAL_BUTTON
        {
            return Err("Некорректный граф".into());
        }
    }
    let mut cycle_ids = HashSet::new();
    for cycle in &cycles {
        if cycle.length < 2
            || cycle.length as usize != cycle.nodes.len()
            || cycle.nodes.len() + cycle.heads.len() > 1_048_576
            || !cycle_ids.insert(cycle.index)
            || cycle.index as usize >= nodes.len()
            || cycle.nodes.iter().chain(&cycle.heads).any(|&n| n >= len)
        {
            return Err("Некорректное кольцо".into());
        }
    }
    for node in &nodes {
        if node.head_type > CYCLE_HEAD_TYPE_XOR_WRITE || node.cycle_idx < -1 {
            return Err("Некорректная головка кольца".into());
        }
        if node.cycle_idx >= 0 && !cycle_ids.contains(&(node.cycle_idx as u32)) {
            return Err("Узел ссылается на отсутствующее кольцо".into());
        }
    }
    core::init(test.seed.unwrap_or(123456789));
    core::ensure_node_capacity_export(len);
    core::ensure_chunk_capacity_export(1);
    for (index, node) in nodes.iter().enumerate() {
        // Only this process owns the engine. All indices and capacities were checked above.
        unsafe {
            let ptr = core::get_staging_buffer_ptr();
            for (i, value) in node.links.iter().chain(&node.detectors).enumerate() {
                *ptr.add(i) = *value;
            }
        }
        core::update_node_state(
            index as u32,
            node.node_type,
            node.entry as i32,
            node.additional as i32,
            0,
            node.cycle_idx,
            node.cycle_offset,
            node.head_type,
            0,
            node.links.len() as u32,
            node.detectors.len() as u32,
            node.detected,
            node.blocked,
        );
    }
    for cycle in &cycles {
        unsafe {
            let ptr = core::get_staging_buffer_ptr();
            for (i, value) in cycle.nodes.iter().chain(&cycle.heads).enumerate() {
                *ptr.add(i) = *value;
            }
        }
        core::on_cycle_build_export(
            cycle.index,
            cycle.length,
            cycle.nodes.len() as u32,
            cycle.heads.len() as u32,
        );
    }
    core::reset_export();
    let mut previous_inputs = vec![0u8; inputs.len()];
    let mut traces = vec![Vec::with_capacity(samples); outputs.len()];
    let mut observations = vec![Vec::with_capacity(samples); observed.len()];
    let mut failures = Vec::new();
    let mut failed_count = 0usize;
    let mut checked_samples = 0usize;
    let mut sample = 0usize;
    let mut frame_end = test.frame_ticks.as_ref().map_or(hold, |frames| frames[0]);
    for tick in 0..test.ticks {
        for (p, &index) in inputs.iter().enumerate() {
            let value = test.inputs[p].values[sample].expect("input values validated above");
            if value != previous_inputs[p] {
                let state = get_state();
                let delta = if value == 1 { 1 } else { 255 };
                state.nodes[index].signals_count =
                    state.nodes[index].signals_count.wrapping_add(delta);
                state.mark_node_as_changed(index as u32);
                previous_inputs[p] = value;
            }
        }
        core::run_tick();
        if tick + 1 != frame_end {
            continue;
        }
        for (p, &index) in outputs.iter().enumerate() {
            let value = u8::from(core::get_node_signal_export(index as u32) == NODE_SIGNAL_ACTIVE);
            traces[p].push(value);
            if let Some(expected) = test.expect[p].values[sample] {
                checked_samples += 1;
                if value != expected {
                    failed_count += 1;
                    if failures.len() < 100 {
                        failures.push(json!({"tick": tick + 1, "at": test.expect[p].at, "expected": expected, "actual": value}));
                    }
                }
            }
        }
        for (p, &index) in observed.iter().enumerate() {
            observations[p].push(u8::from(core::get_node_signal_export(index as u32) == NODE_SIGNAL_ACTIVE));
        }
        sample += 1;
        if sample < samples {
            frame_end += test
                .frame_ticks
                .as_ref()
                .map_or(hold, |frames| frames[sample]);
        }
    }
    Ok(json!({
        "passed": if checked_samples == 0 { None } else { Some(failed_count == 0) }, "ticks": test.ticks, "nodes": nodes.len(),
        "hold_ticks": hold,
        "frame_ticks": test.frame_ticks,
        "optimized_cycles": cycles.len(), "failure_count": failed_count,
        "failures": failures,
        "checked_samples": checked_samples,
        "observed_samples": observed.len() * samples,
        "outputs": test.expect.iter().enumerate().map(|(p, port)| json!({"at": port.at, "values": traces[p]})).collect::<Vec<_>>(),
        "observations": test.observe.iter().enumerate().map(|(p, at)| json!({"at": at, "values": observations[p]})).collect::<Vec<_>>(),
        "profile": "GraphDLC-01232bd", "verified_against_current_game": false,
    }))
}

fn main() {
    let result = (|| -> Result<Value, String> {
        let mut text = String::new();
        io::stdin()
            .read_to_string(&mut text)
            .map_err(|e| e.to_string())?;
        let request = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        run(request)
    })();
    match result {
        Ok(report) => {
            println!("{}", serde_json::to_string(&report).unwrap());
            if report["passed"] == false {
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("Ошибка: {error}");
            std::process::exit(2);
        }
    }
}
