package api

import (
	"testing"
	"time"
)

func TestWeightedQuotaRecoveryDuration(t *testing.T) {
	tests := []struct {
		name  string
		input []time.Duration
		want  time.Duration
	}{
		{name: "fallback", want: 24 * time.Hour},
		{name: "single", input: []time.Duration{18 * time.Hour}, want: 18 * time.Hour},
		{name: "newest weighs most", input: []time.Duration{12 * time.Hour, 24 * time.Hour}, want: 16 * time.Hour},
		{name: "minimum probe resolution", input: []time.Duration{time.Minute}, want: 5 * time.Minute},
		{name: "official upper bound", input: []time.Duration{30 * time.Hour}, want: 24 * time.Hour},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := weightedQuotaRecoveryDuration(test.input); got != test.want {
				t.Fatalf("got %v, want %v", got, test.want)
			}
		})
	}
}
