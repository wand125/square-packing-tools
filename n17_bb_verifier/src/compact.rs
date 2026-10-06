//! Lossless, interned JSON used only for the two-pass tree metadata.

use std::collections::HashMap;
use std::collections::hash_map::{Entry, RandomState};
use std::hash::BuildHasher;

use serde_json::Value;

#[derive(Eq, Hash, PartialEq)]
enum Packed {
    Null,
    Bool(bool),
    String(Box<str>),
    // Keep the number itself to avoid a second floating-point parse. The text
    // also distinguishes signed zero when interning (Number equality does not).
    Number(Box<Number>),
    Array(Box<[usize]>),
    Object(Box<[(String, usize)]>),
}

#[derive(Eq, Hash, PartialEq)]
struct Number {
    text: Box<str>,
    value: serde_json::Number,
}

#[derive(Default)]
pub(crate) struct Values {
    entries: Vec<Packed>,
    lookup: HashMap<u64, usize>,
    hasher: RandomState,
}

impl Values {
    pub(crate) fn insert(&mut self, value: &Value) -> usize {
        let packed = match value {
            Value::Array(values) => Packed::Array(values.iter().map(|v| self.insert(v)).collect()),
            Value::Object(values) => Packed::Object(
                values
                    .iter()
                    .map(|(k, v)| (k.clone(), self.insert(v)))
                    .collect(),
            ),
            Value::Null => Packed::Null,
            Value::Bool(value) => Packed::Bool(*value),
            Value::String(value) => Packed::String(value.as_str().into()),
            Value::Number(value) => Packed::Number(Box::new(Number {
                text: value.to_string().into(),
                value: value.clone(),
            })),
        };
        let hash = self.hasher.hash_one(&packed);
        self.intern(packed, hash)
    }

    fn intern(&mut self, packed: Packed, mut hash: u64) -> usize {
        loop {
            match self.lookup.entry(hash) {
                Entry::Occupied(entry) => {
                    let index = *entry.get();
                    if self.entries[index] == packed {
                        return index;
                    }
                    // Hashes only locate candidates: equality is always checked.
                    // Probe another key on collision, without duplicating values
                    // or allocating a separate collision list for every entry.
                    hash = hash.wrapping_add(1);
                }
                Entry::Vacant(entry) => {
                    let index = self.entries.len();
                    self.entries.push(packed);
                    entry.insert(index);
                    return index;
                }
            }
        }
    }

    pub(crate) fn get(&self, index: usize) -> Value {
        match &self.entries[index] {
            Packed::Null => Value::Null,
            Packed::Bool(value) => Value::Bool(*value),
            Packed::String(value) => Value::String(value.to_string()),
            Packed::Number(number) => Value::Number(number.value.clone()),
            Packed::Array(values) => Value::Array(values.iter().map(|&i| self.get(i)).collect()),
            Packed::Object(values) => Value::Object(
                values
                    .iter()
                    .map(|(k, i)| (k.clone(), self.get(*i)))
                    .collect(),
            ),
        }
    }

    pub(crate) fn finish(&mut self) {
        // No interning is needed during either verification pass.
        self.lookup = HashMap::new();
    }
}

const FIELDS: [&str; 5] = ["angles", "windows", "closed", "split", "final"];

pub(crate) struct Node {
    fields: [usize; 5],
    pub(crate) open: bool,
    pub(crate) chunk: usize,
    pub(crate) depth: Option<usize>,
}

impl Node {
    pub(crate) fn new(value: &Value, values: &mut Values) -> Self {
        Self {
            fields: FIELDS.map(|key| {
                if key == "split" && value[key].get("tighten").is_some() {
                    // Replay reads E from the streamed chunk, never from tree metadata.
                    let mut split = value[key].clone();
                    if let Some(items) = split["tighten"].as_array_mut()
                        && items.len() == 2
                    {
                        items[0] = Value::Null;
                    }
                    values.insert(&split)
                } else {
                    values.insert(&value[key])
                }
            }),
            open: value["closed"].is_null(),
            chunk: 0,
            depth: None,
        }
    }

    pub(crate) fn json(&self, values: &Values) -> Value {
        Value::Object(
            FIELDS
                .into_iter()
                .zip(self.fields)
                .map(|(k, i)| (k.into(), values.get(i)))
                .collect(),
        )
    }

    pub(crate) fn parent(&self, values: &Values) -> Value {
        serde_json::json!({"final": values.get(self.fields[4])})
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn hash_collisions_do_not_merge_different_values() {
        let mut values = Values::default();
        let first = values.intern(Packed::String("first".into()), u64::MAX);
        let second = values.intern(Packed::String("second".into()), u64::MAX);
        assert_ne!(first, second);
        assert_eq!(
            first,
            values.intern(Packed::String("first".into()), u64::MAX)
        );
        assert_eq!(
            second,
            values.intern(Packed::String("second".into()), u64::MAX)
        );
        values.finish();
        assert_eq!(values.get(first), json!("first"));
        assert_eq!(values.get(second), json!("second"));
    }

    #[test]
    fn retained_fixture_metadata_is_lossless() {
        let directory = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/small-certificate");
        let mut values = Values::default();
        let mut originals = Vec::new();
        let mut packed = Vec::new();
        for entry in std::fs::read_dir(&directory).expect("fixture directory") {
            let path = entry.expect("fixture entry").path();
            let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            let Some(name) = name.strip_suffix(".json.gz") else {
                continue;
            };
            let data = crate::read_named(&directory, name).expect("fixture JSON");
            if let Some(nodes) = data["nodes"].as_array() {
                for node in nodes {
                    packed.push(Node::new(node, &mut values));
                    originals.push(node.clone());
                }
            }
        }
        assert_eq!(originals.len(), 83);
        values.finish();
        for (node, original) in packed.iter().zip(originals) {
            let restored = node.json(&values);
            for field in FIELDS {
                assert_eq!(restored[field].to_string(), original[field].to_string());
            }
            assert_eq!(node.open, original["closed"].is_null());
            assert_eq!(node.parent(&values)["final"], original["final"]);
            for sorted in [false, true] {
                assert_eq!(
                    crate::state(&restored, sorted),
                    crate::state(&original, sorted)
                );
            }
            if node.open {
                assert_eq!(
                    crate::expected_children(&restored),
                    crate::expected_children(&original)
                );
            }
        }
    }

    #[test]
    fn sharing_preserves_json_text_and_unusual_values() {
        let mut values = Values::default();
        let source: Value = serde_json::from_str(
            r#"[null,false,true,0,0.0,-0.0,1,1.0,18446744073709551615,"1/2","2/4",{"z":[],"a":[12,2,2.0]},[["1/2","2/4"],["1/2","2/4"]]]"#,
        ).expect("JSON");
        let key = values.insert(&source);
        let size = values.entries.len();
        assert_eq!(key, values.insert(&source));
        assert_eq!(size, values.entries.len());
        values.finish();
        assert_eq!(source.to_string(), values.get(key).to_string());
        // Invalid shapes must survive loading so the original checks reject them.
        for source in [json!({"closed":false,"split":[],"final":42}), json!({})] {
            let node = Node::new(&source, &mut values);
            let restored = node.json(&values);
            for field in FIELDS {
                assert_eq!(restored[field], source[field]);
            }
        }
    }
}
