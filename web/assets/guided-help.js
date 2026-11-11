// Practice sends are local. The reply lesson uses the selected family post for context.
const lessons = {
  intro: ['반가워요! 저는 토닥이에요.', '손가락이 가리키는 곳을 따라 해보세요.'],
  read: ['소식을 위아래로 움직여 봐요.', '글을 아래로 내렸다가 위로 올려보세요.'],
  write: ['가족에게 소식을 올려봐요.', '소식 쓰기를 누르고 글이나 연습 사진을 올려보세요.'],
  listen: ['소식을 소리로 들어봐요.', '토닥 도우미에서 음성으로 듣기를 찾아보세요.'],
  day: ['하루 소식을 찾아봐요.', '토닥 도우미에서 오늘 가족의 하루를 열어보세요.'],
  reply: ['가족 소식에 답장해 봐요.', '댓글을 글로 쓰거나 말로 답장하는 방법을 연습해요.'],
  end: ['잘하셨어요!', '토닥 도우미의 도움말에서 다시 연습할 수 있어요.'],
};
const samplePhoto = '<img class="help-picture" alt="연습 사진" src="/web/assets/assistant_character.png">';
const button = (action, label) => `<button type="button" class="button secondary full" data-help="${action}">${label}</button>`;

export class GuidedHelp {
  open({ post = null, replyOnly = false, onReplyShown = () => {}, onClose = () => {} } = {}) {
    if (this.dialog?.open) return;
    this.steps = replyOnly ? [] : ['intro', 'read', 'write', 'listen', 'day'];
    if (post) this.steps.push('reply');
    this.steps.push('end');
    this.post = post;
    this.onReplyShown = onReplyShown;
    this.index = 0;
    const dialog = document.createElement('dialog');
    this.dialog = dialog;
    dialog.className = 'guided-help';
    dialog.setAttribute('aria-label', '토닥 사용 안내');
    dialog.addEventListener('close', () => {
      clearTimeout(this.advance);
      dialog.remove();
      onClose();
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    this.render();
  }

  point(target) {
    if (!this.hand) {
      this.hand = document.createElement('span');
      this.hand.className = 'help-hand';
      this.hand.setAttribute('aria-hidden', 'true');
      this.hand.innerHTML = '<img src="/web/assets/assistant_character.png" alt=""><span>👉</span>';
    }
    target.before(this.hand);
  }

  render() {
    clearTimeout(this.advance);
    const lesson = this.steps[this.index];
    const [title, instruction] = lessons[lesson];
    const dialog = this.dialog;
    dialog.innerHTML = `<div class="help-stage"><header><span>사용 안내 ${this.index + 1} / ${this.steps.length}</span>${button('skip', '나중에 보기')}</header>
      <div class="help-feed"><h2>${title}</h2><p>${instruction}</p><p class="help-note">연습용 · 실제 가족방에 저장되지 않아요</p>
      <div class="help-practice"></div></div><footer>${button('next', lesson === 'end' ? '가족 소식으로 돌아가기' : '다음')}${this.index ? button('previous','이전') : ''}</footer></div>`;
    const find = selector => dialog.querySelector(selector);
    const practice = find('.help-practice'), feed = find('.help-feed'), next = find('[data-help="next"]');
    find('[data-help="skip"]').onclick = () => dialog.close();
    const previous = find('[data-help="previous"]');
    if (previous) previous.onclick = () => { this.index--; this.render(); };
    next.disabled = true;
    next.onclick = () => {
      if (lesson === 'end') dialog.close();
      else { this.index++; this.render(); }
    };
    const done = () => { next.disabled = false; this.point(next); };
    if (lesson === 'intro' || lesson === 'end') {
      practice.innerHTML = samplePhoto;
      done();
    } else if (lesson === 'read') {
      practice.innerHTML = `<p>오늘은 따뜻한 차를 마시며 쉬고 있어요.</p>${samplePhoto}<p>가족 여러분도 좋은 하루 보내세요!</p><div class="help-scroll-space"></div>`;
      this.point(practice.firstElementChild);
      let previousY = 0, down = false;
      feed.onscroll = () => {
        if (feed.scrollTop > 48) down = true;
        if (down && feed.scrollTop < previousY && next.disabled) {
          done();
          this.advance = setTimeout(() => { if (dialog.open) next.click(); }, 700);
        }
        previousY = feed.scrollTop;
      };
    } else if (lesson === 'reply' || lesson === 'write') {
      const reply = lesson === 'reply';
      practice.innerHTML = (reply ? '<strong class="help-author"></strong><p class="help-caption"></p>' : '') + button(reply ? 'comment' : 'compose', reply ? '댓글 달기' : '소식 쓰기');
      if (reply) {
        find('.help-author').textContent = `${this.post.author_name || '가족'}님의 소식`;
        find('.help-caption').textContent = this.post.caption || '사진으로 전한 소식이에요.';
        this.onReplyShown();
      }
      const open = practice.querySelector('button');
      this.point(open);
      open.onclick = () => this.form(practice, reply, done);
    } else {
      practice.innerHTML = button('bot','토닥 도우미');
      const bot = practice.querySelector('button');
      this.point(bot);
      bot.onclick = () => {
        const listen = lesson === 'listen';
        practice.innerHTML = button(lesson, listen ? '음성으로 듣기' : '오늘 가족의 하루');
        const action = practice.querySelector('button');
        this.point(action);
        action.onclick = () => {
          practice.innerHTML = listen ? '<p>연습용 듣기를 열었어요.</p>' :
            '<h3>연습용 하루 달력</h3><div class="month-grid">' + Array.from({length:28}, (_,i) => `<span>${i+1}</span>`).join('') + '</div>';
          done();
        };
      };
    }
  }

  form(panel, reply, done) {
    panel.innerHTML = `<form><label>${reply ? '연습 댓글' : '연습 게시글'}<textarea class="help-comment" placeholder="여기에 적어 주세요"></textarea></label>
      ${button(reply ? 'voice' : 'photo', reply ? '말로 댓글 남기기' : '연습 사진 추가')}<div role="status"></div>
      <button type="submit" class="button primary full">${reply ? '댓글 남기기' : '가족에게 전하기'}</button></form>`;
    const form = panel.querySelector('form'), input = form.querySelector('textarea');
    const alternate = form.querySelector('[type=button]'), send = form.querySelector('[type=submit]');
    const preview = form.querySelector('[role=status]');
    let photo = false;
    const update = () => {
      send.disabled = !photo && !input.value.trim();
      this.point(send.disabled ? input.parentElement : send);
    };
    alternate.onclick = () => {
      if (reply) {
        input.value = '좋은 하루 보내세요!';
        preview.textContent = '음성 예시예요. 내용을 확인하고 보내세요.';
      } else {
        photo = true;
        preview.innerHTML = samplePhoto;
      }
      alternate.disabled = true;
      update();
    };
    input.oninput = update;
    form.onsubmit = event => {
      event.preventDefault();
      if (send.disabled) return;
      panel.innerHTML = `<strong>${reply ? '연습 댓글을 남겼어요.' : '연습 소식을 올렸어요.'}</strong>${photo ? samplePhoto : ''}<p></p>`;
      panel.querySelector('p').textContent = input.value;
      done();
    };
    update();
  }
}
