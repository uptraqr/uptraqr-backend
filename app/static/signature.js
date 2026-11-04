document.querySelectorAll('[data-copy]').forEach(function(b){
  b.addEventListener('click',function(){
    var el=document.getElementById(b.dataset.copy), r=document.createRange(), s=window.getSelection();
    r.selectNodeContents(el); s.removeAllRanges(); s.addRange(r);
    try{document.execCommand('copy');}catch(e){}
    s.removeAllRanges(); b.nextElementSibling.hidden=false;
  });
});
