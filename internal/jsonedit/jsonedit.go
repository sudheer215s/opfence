// Package jsonedit reads and writes JSON settings files without reordering
// them, so that adding one entry to a user's settings changes only that
// entry. Objects keep their keys in file order (duplicates included, where
// the last one counts, as for JSON.parse); numbers keep their text.
package jsonedit

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

// Object is a JSON object with its members in order.
type Object struct {
	Members []Member
}

// Member is one key and value of an Object.
type Member struct {
	Key   string
	Value any
}

// Values are *Object, []any, string, json.Number, bool or nil.

// Get returns the value of key (its last occurrence) and whether it is set.
func (o *Object) Get(key string) (any, bool) {
	for i := len(o.Members) - 1; i >= 0; i-- {
		if o.Members[i].Key == key {
			return o.Members[i].Value, true
		}
	}
	return nil, false
}

// Set replaces the value of key's last occurrence, or appends key.
func (o *Object) Set(key string, v any) {
	for i := len(o.Members) - 1; i >= 0; i-- {
		if o.Members[i].Key == key {
			o.Members[i].Value = v
			return
		}
	}
	o.Members = append(o.Members, Member{key, v})
}

// Delete removes every occurrence of key.
func (o *Object) Delete(key string) {
	out := o.Members[:0]
	for _, m := range o.Members {
		if m.Key != key {
			out = append(out, m)
		}
	}
	o.Members = out
}

// Len is the number of members.
func (o *Object) Len() int { return len(o.Members) }

// Parse reads one JSON value.
func Parse(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := parseValue(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("unexpected data after the JSON value")
	}
	return v, nil
}

func parseValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		if err == io.EOF {
			return nil, io.ErrUnexpectedEOF
		}
		return nil, err
	}
	switch t := tok.(type) {
	case json.Delim:
		switch t {
		case '{':
			o := &Object{}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				k, ok := kt.(string)
				if !ok {
					return nil, fmt.Errorf("object key is %v, not a string", kt)
				}
				v, err := parseValue(dec)
				if err != nil {
					return nil, err
				}
				o.Members = append(o.Members, Member{k, v})
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return o, nil
		case '[':
			a := []any{}
			for dec.More() {
				v, err := parseValue(dec)
				if err != nil {
					return nil, err
				}
				a = append(a, v)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return a, nil
		}
		return nil, fmt.Errorf("unexpected %v", t)
	default:
		return t, nil
	}
}

// Marshal writes v indented by two spaces, as JSON.stringify(v, null, 2)
// does, with a final newline.
func Marshal(v any) ([]byte, error) {
	var b bytes.Buffer
	if err := write(&b, v, ""); err != nil {
		return nil, err
	}
	b.WriteByte('\n')
	return b.Bytes(), nil
}

func write(b *bytes.Buffer, v any, indent string) error {
	switch t := v.(type) {
	case *Object:
		if t == nil {
			b.WriteString("null")
			return nil
		}
		if len(t.Members) == 0 {
			b.WriteString("{}")
			return nil
		}
		b.WriteString("{\n")
		for i, m := range t.Members {
			b.WriteString(indent + "  ")
			if err := writeString(b, m.Key); err != nil {
				return err
			}
			b.WriteString(": ")
			if err := write(b, m.Value, indent+"  "); err != nil {
				return err
			}
			if i < len(t.Members)-1 {
				b.WriteByte(',')
			}
			b.WriteByte('\n')
		}
		b.WriteString(indent + "}")
	case []any:
		if len(t) == 0 {
			b.WriteString("[]")
			return nil
		}
		b.WriteString("[\n")
		for i, e := range t {
			b.WriteString(indent + "  ")
			if err := write(b, e, indent+"  "); err != nil {
				return err
			}
			if i < len(t)-1 {
				b.WriteByte(',')
			}
			b.WriteByte('\n')
		}
		b.WriteString(indent + "]")
	case string:
		return writeString(b, t)
	case json.Number:
		if !json.Valid([]byte(t)) {
			return fmt.Errorf("invalid number %q", string(t))
		}
		b.WriteString(string(t))
	case bool:
		if t {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case nil:
		b.WriteString("null")
	case int:
		fmt.Fprintf(b, "%d", t)
	default:
		return fmt.Errorf("jsonedit: cannot write %T", v)
	}
	return nil
}

func writeString(b *bytes.Buffer, s string) error {
	var sb bytes.Buffer
	enc := json.NewEncoder(&sb)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(s); err != nil {
		return err
	}
	b.Write(bytes.TrimSuffix(sb.Bytes(), []byte("\n")))
	return nil
}

// StripComments returns data with // and /* */ comments outside strings
// replaced by spaces (newlines kept), as the strip-json-comments package
// Gemini CLI uses does, and whether there were any.
func StripComments(data []byte) ([]byte, bool) {
	out := []byte(string(data))
	found := false
	inString := false
	for i := 0; i < len(out); i++ {
		c := out[i]
		if inString {
			switch c {
			case '\\':
				i++
			case '"':
				inString = false
			}
			continue
		}
		switch {
		case c == '"':
			inString = true
		case c == '/' && i+1 < len(out) && out[i+1] == '/':
			found = true
			for ; i < len(out) && out[i] != '\n'; i++ {
				if out[i] != '\r' {
					out[i] = ' '
				}
			}
		case c == '/' && i+1 < len(out) && out[i+1] == '*':
			found = true
			end := bytes.Index(out[i+2:], []byte("*/"))
			stop := len(out)
			if end >= 0 {
				stop = i + 2 + end + 2
			}
			for j := i; j < stop; j++ {
				if out[j] != '\n' && out[j] != '\r' {
					out[j] = ' '
				}
			}
			i = stop - 1
		}
	}
	return out, found
}

// IsBlank reports whether data holds only white space.
func IsBlank(data []byte) bool {
	return strings.TrimSpace(string(data)) == ""
}
