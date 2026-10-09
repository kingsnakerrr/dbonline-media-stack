package api

import (
	"strings"
	"time"

	"rclone-manager/internal/models"
)

const (
	remoteQuotaProbeInterval      = 5 * time.Minute
	officialQuotaRecoveryFallback = 24 * time.Hour
	quotaRecoveryHistoryLimit     = 5
)

type quotaRecoveryPrediction struct {
	Duration     time.Duration
	SampleCount  int
	LastDuration time.Duration
	Source       string
}

// predictRemoteQuotaRecovery learns only from the same rclone remote. Recent
// observations carry more weight so a changed reset pattern is reflected
// without discarding the older samples after one unusual recovery.
func predictRemoteQuotaRecovery(remote string) quotaRecoveryPrediction {
	var rows []models.RemoteQuotaRecovery
	db.Where("lower(remote_name) = ?", strings.ToLower(strings.TrimSpace(remote))).
		Order("recovered_at DESC").
		Limit(quotaRecoveryHistoryLimit).
		Find(&rows)

	samples := make([]time.Duration, 0, len(rows))
	for _, row := range rows {
		if row.DurationSeconds > 0 {
			samples = append(samples, time.Duration(row.DurationSeconds)*time.Second)
		}
	}
	if len(samples) == 0 {
		return quotaRecoveryPrediction{
			Duration: officialQuotaRecoveryFallback,
			Source:   "official_24h_fallback",
		}
	}

	return quotaRecoveryPrediction{
		Duration:     weightedQuotaRecoveryDuration(samples),
		SampleCount:  len(samples),
		LastDuration: samples[0],
		Source:       "account_history",
	}
}

func weightedQuotaRecoveryDuration(samples []time.Duration) time.Duration {
	if len(samples) == 0 {
		return officialQuotaRecoveryFallback
	}
	var weightedSeconds int64
	var totalWeight int64
	for i, sample := range samples {
		weight := int64(len(samples) - i)
		weightedSeconds += int64(sample/time.Second) * weight
		totalWeight += weight
	}
	duration := time.Duration(weightedSeconds/totalWeight) * time.Second
	if duration < remoteQuotaProbeInterval {
		return remoteQuotaProbeInterval
	}
	if duration > officialQuotaRecoveryFallback {
		return officialQuotaRecoveryFallback
	}
	return duration
}

func recordRemoteQuotaRecovery(state *models.RemoteQuotaState, recoveredAt time.Time) {
	if state == nil || state.QuotaErrorAt == nil || !recoveredAt.After(*state.QuotaErrorAt) {
		return
	}
	record := models.RemoteQuotaRecovery{
		RemoteName:      strings.TrimSpace(state.RemoteName),
		QuotaErrorAt:    *state.QuotaErrorAt,
		RecoveredAt:     recoveredAt,
		DurationSeconds: int64(recoveredAt.Sub(*state.QuotaErrorAt).Seconds()),
	}
	// A successful probe can only close a limit period once. The composite
	// unique index also prevents duplicate history if a process restarts while
	// persisting the state transition.
	_ = db.Where("remote_name = ? AND quota_error_at = ?", record.RemoteName, record.QuotaErrorAt).
		FirstOrCreate(&record).Error
}
