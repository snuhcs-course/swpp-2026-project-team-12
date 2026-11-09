import { icon } from './icons.js';

// A separate local practice surface; it never uses fetch, microphone APIs, or the real feed.
export class GuidedHelp {
  open(onFinish = () => {}) {
    if (this.dialog?.open) return;
    this.step = 0; this.onFinish = onFinish;
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'guided-help'; this.dialog.setAttribute('aria-label', '토닥 사용 안내');
    this.dialog.addEventListener('close', () => { clearTimeout(this.advance); this.dialog.remove(); this.onFinish(); }, { once: true });
    document.body.append(this.dialog); this.render(); this.dialog.showModal();
  }
  done(auto = false) {
    if (this.completed) return;
    this.completed = true;
    const next = this.dialog.querySelector('[data-help="next"]'); next.disabled = false; next.textContent = '다음';
    if (auto) { const step = this.step; this.advance = setTimeout(() => { if (this.dialog.open && this.step === step) { this.step++; this.render(); } }, 700); }
  }
  render() {
    clearTimeout(this.advance); this.completed = [0, 5].includes(this.step);
    const copy = [
      ['반가워요! 저는 토닥이에요.', '가족의 글과 별도로 준비한 가상 소식으로 함께 연습해요.'],
      ['소식을 위아래로 움직여 봐요.', '사진 위에서 아래로 내렸다가, 위로도 한 번 올려보세요.'],
      ['댓글로 마음을 전해요.', '댓글 달기를 누른 뒤 글로 쓰거나 말로 남기는 방법을 연습해요.'],
      ['소식을 소리로 들어봐요.', '도우미를 누르고 음성으로 듣기를 골라보세요.'],
      ['하루와 추억도 여기 있어요.', '도우미를 누르고 오늘 가족의 하루를 열어보세요.'],
      ['잘하셨어요!', '언제든 도우미의 도움말에서 다시 연습할 수 있어요. 원래 보던 소식으로 돌아갈게요.'],
    ][this.step];
    this.dialog.innerHTML = `<div class="help-stage"><header><strong>토닥</strong><span>연습용 소식 · 실제 가족방에 저장되지 않아요</span></header><div class="help-feed"><article class="post-card"><header class="post-author"><strong>토닥 도우미 · 연습용</strong></header><img class="help-picture" src="/web/assets/assistant_character.png" alt="연습용 소식 사진"><p class="post-body">오늘은 따뜻한 차를 마시며 쉬고 있어요.<br>가족 여러분도 좋은 하루 보내세요!</p><div class="help-practice"><button type="button" data-help="comment" class="button secondary full">${icon('comment')}댓글 달기</button></div><section class="help-sample-comments"><h3>가족의 댓글</h3><p>따뜻한 차 한 잔 좋겠어요. 좋은 하루 보내세요!</p></section>${this.step === 1 ? '<div class="help-scroll-space"><p>글과 댓글을 천천히 읽어보세요.</p></div>' : ''}</article></div><button type="button" class="help-bot" data-help="bot" aria-label="토닥 도우미 열기"><img src="/web/assets/assistant_character.png" alt=""><strong>토닥 도우미</strong></button><div class="help-menu" hidden></div><div class="help-shade" aria-hidden="true"></div><section class="help-coach ${[2,3,4].includes(this.step) ? 'coach-top' : ''}"><div class="help-step"><span>사용 안내 ${this.step + 1} / 6</span><button type="button" data-help="skip">나중에 보기</button></div><h2>${copy[0]}</h2><p>${copy[1]}</p><button class="button primary full" type="button" data-help="next" ${this.completed ? '' : 'disabled'}>${this.step === 5 ? '가족 소식으로 돌아가기' : this.completed ? '다음' : '직접 해보세요'}</button>${this.step ? '<button type="button" data-help="previous" class="button quiet full">이전</button>' : ''}</section></div>`;
    const find = selector => this.dialog.querySelector(selector);
    this.target = find([0,3,4,5].includes(this.step) ? '.help-bot' : this.step === 1 ? '.help-feed' : '[data-help="comment"]');
    find('[data-help="skip"]').onclick = () => this.dialog.close();
    find('[data-help="next"]').onclick = () => { if (this.step === 5) this.dialog.close(); else if (this.completed) { this.step++; this.render(); } };
    find('[data-help="previous"]')?.addEventListener('click', () => { this.step--; this.render(); });
    const feed = find('.help-feed'); let previous = 0, down = false;
    feed.onscroll = () => {
      if (this.step === 1) { if (feed.scrollTop > 80) down = true; if (down && previous - feed.scrollTop > 10) this.done(true); previous = feed.scrollTop; }
      this.spotlight();
    };
    find('[data-help="comment"]').onclick = () => {
      if (this.step !== 2) return;
      const practice = find('.help-practice');
      practice.innerHTML = '<form><label>연습 댓글<input class="help-comment" placeholder="따뜻한 한마디를 적어 주세요" required></label><button type="submit" class="button primary full">댓글 남기기</button><button type="button" class="button secondary full" data-help="voice">말로 댓글 남기기</button><p class="help-note" role="status"></p></form>';
      practice.querySelector('form').onsubmit = event => { event.preventDefault(); if (practice.querySelector('input').value.trim()) { practice.querySelector('.help-note').textContent = '연습 댓글을 남겼어요!'; this.done(true); } };
      practice.querySelector('[data-help="voice"]').onclick = () => {
        practice.querySelector('input').value = '좋은 하루 보내세요!';
        practice.querySelector('.help-note').textContent = '연습용 음성 예시예요. 실제 녹음은 하지 않아요.';
        this.done(true);
      };
      this.target = practice; this.positionPractice();
    };
    find('[data-help="bot"]').onclick = () => {
      if (![3,4].includes(this.step)) return;
      const menu = find('.help-menu'); menu.hidden = false;
      menu.innerHTML = `<button type="button" class="button secondary full" data-help="listen">음성으로 듣기</button><button type="button" class="button secondary full" data-help="day">오늘 가족의 하루</button>`;
      const action = find(this.step === 3 ? '[data-help="listen"]' : '[data-help="day"]');
      menu.querySelectorAll('button').forEach(button => { button.disabled = button !== action; });
      action.onclick = () => {
        menu.innerHTML = this.step === 3 ? '<p>연습용 듣기를 열었어요. 실제 소식은 소식 듣기로 들을 수 있어요.</p>' : '<h3>연습용 하루 달력</h3><div class="month-grid">'+Array.from({length:28},(_,i)=>`<span>${i+1}</span>`).join('')+'</div>';
        this.target = menu; this.done(); this.spotlight();
      };
      this.target = action; this.spotlight();
    };
    // Allow only the highlighted practice controls and the guide itself.
    this.dialog.onclick = event => { if (event.target === this.dialog) event.preventDefault(); };
    requestAnimationFrame(() => this.positionPractice());
  }
  positionPractice() {
    if (!this.dialog.open || !this.target) return;
    const feed = this.dialog.querySelector('.help-feed'), coach = this.dialog.querySelector('.help-coach');
    if (this.step === 2) {
      const delta = this.target.getBoundingClientRect().top - coach.getBoundingClientRect().bottom - 16;
      feed.scrollTop += delta;
    }
    this.spotlight();
  }
  spotlight() {
    if (!this.dialog.open || !this.target?.isConnected) return;
    const r = this.target.getBoundingClientRect(), stage = this.dialog.querySelector('.help-stage').getBoundingClientRect();
    const shade = this.dialog.querySelector('.help-shade');
    Object.assign(shade.style, { left: `${r.left-stage.left-5}px`, top: `${r.top-stage.top-5}px`, width: `${r.width+10}px`, height: `${r.height+10}px` });
  }
}
