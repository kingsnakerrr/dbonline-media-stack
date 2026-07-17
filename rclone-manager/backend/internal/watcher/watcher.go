package watcher

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"rclone-manager/internal/models"
	"rclone-manager/internal/rclone"
)

type Watcher struct {
	watchers    map[uint]*fsnotify.Watcher
	executors   map[uint]*rclone.Executor
	tasks       map[uint]*models.Task
	retryTimers map[uint]*time.Timer
	mu          sync.RWMutex
}

func NewWatcher(executor *rclone.Executor) *Watcher {
	return &Watcher{
		watchers:    make(map[uint]*fsnotify.Watcher),
		executors:   make(map[uint]*rclone.Executor),
		tasks:       make(map[uint]*models.Task),
		retryTimers: make(map[uint]*time.Timer),
	}
}

func parseMinAge(value string) time.Duration {
	value = strings.TrimSpace(value)
	if value == "" {
		return 3 * time.Minute
	}
	d, err := time.ParseDuration(value)
	if err != nil || d <= 0 {
		return 3 * time.Minute
	}
	return d
}

func (w *Watcher) StartTaskWatch(task *models.Task, executor *rclone.Executor) error {
	if !task.WatchEnabled {
		return nil
	}
	// Watching only works for local source directories
	if task.SourceType == "remote" {
		log.Printf("Skipping watch for task %d: source is remote", task.ID)
		return nil
	}

	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}

	// Watch source directory
	if err := watcher.Add(task.SourceDir); err != nil {
		watcher.Close()
		return err
	}

	// Also watch subdirectories
	filepath.Walk(task.SourceDir, func(path string, info os.FileInfo, err error) error {
		if err == nil && info.IsDir() {
			watcher.Add(path)
		}
		return nil
	})

	w.mu.Lock()
	w.watchers[task.ID] = watcher
	w.executors[task.ID] = executor
	w.tasks[task.ID] = task
	w.mu.Unlock()

	go w.watchLoop(task.ID, watcher, executor)

	log.Printf("Started watching task %d: %s", task.ID, task.SourceDir)
	return nil
}

func (w *Watcher) StopTaskWatch(taskID uint) {
	w.mu.Lock()
	if watcher, exists := w.watchers[taskID]; exists {
		watcher.Close()
		delete(w.watchers, taskID)
		delete(w.executors, taskID)
		delete(w.tasks, taskID)
		if timer, ok := w.retryTimers[taskID]; ok {
			timer.Stop()
			delete(w.retryTimers, taskID)
		}
	}
	w.mu.Unlock()
	log.Printf("Stopped watching task %d", taskID)
}

func (w *Watcher) triggerMove(taskID uint, executor *rclone.Executor, reason string) {
	w.mu.RLock()
	task := w.tasks[taskID]
	w.mu.RUnlock()

	if task != nil && !executor.IsRunning(taskID) {
		log.Printf("%s for task %d, triggering move", reason, taskID)
		executor.ExecuteMove(task)
	}
}

func (w *Watcher) scheduleStableRetry(taskID uint, executor *rclone.Executor, delay time.Duration) {
	if delay <= 0 {
		delay = 3 * time.Minute
	}
	delay += 15 * time.Second

	w.mu.Lock()
	if timer, ok := w.retryTimers[taskID]; ok {
		timer.Stop()
	}
	w.retryTimers[taskID] = time.AfterFunc(delay, func() {
		w.triggerMove(taskID, executor, "Stable retry")
	})
	w.mu.Unlock()
}

func (w *Watcher) watchLoop(taskID uint, watcher *fsnotify.Watcher, executor *rclone.Executor) {
	var debounceTimer *time.Timer

	for {
		select {
		case event, ok := <-watcher.Events:
			if !ok {
				return
			}

			if event.Op&fsnotify.Write == fsnotify.Write || event.Op&fsnotify.Create == fsnotify.Create {
				if event.Op&fsnotify.Create == fsnotify.Create {
					if info, err := os.Stat(event.Name); err == nil && info.IsDir() {
						_ = watcher.Add(event.Name)
						filepath.Walk(event.Name, func(path string, info os.FileInfo, err error) error {
							if err == nil && info.IsDir() {
								_ = watcher.Add(path)
							}
							return nil
						})
					}
				}

				w.mu.RLock()
				task := w.tasks[taskID]
				w.mu.RUnlock()
				if task != nil {
					w.scheduleStableRetry(taskID, executor, parseMinAge(task.MinAge))
				}

				// Debounce: wait 10 seconds after last event before triggering
				if debounceTimer != nil {
					debounceTimer.Stop()
				}
				debounceTimer = time.AfterFunc(10*time.Second, func() {
					w.triggerMove(taskID, executor, "Directory change detected")
				})
			}

		case err, ok := <-watcher.Errors:
			if !ok {
				return
			}
			log.Printf("Watcher error for task %d: %v", taskID, err)
		}
	}
}

func (w *Watcher) RestartTaskWatch(task *models.Task, executor *rclone.Executor) error {
	w.StopTaskWatch(task.ID)
	return w.StartTaskWatch(task, executor)
}
